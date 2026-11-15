"""Parser and normalizer for GoodWork (Canada) postings."""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from .models import RawGoodworkJob

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str | None) -> str | None:
    """Strip HTML tags and unescape entities."""
    if not text:
        return None
    unescaped = html.unescape(text)
    clean = _TAG_RE.sub(" ", unescaped)
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip() or None


def _parse_goodwork_date(date_str: str | None) -> datetime | None:
    """Parse dates like 'Nov 13 2026' or 'November 13, 2026'."""
    if not date_str:
        return None
    clean = date_str.replace(",", "").strip()
    for fmt in ("%b %d %Y", "%B %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            pass
    return None


class GoodworkParser:
    """Transforms RawGoodworkJob instances into CleanedJob records."""

    def parse_job(self, raw: RawGoodworkJob) -> CleanedJob | None:
        """Parse a single RawGoodworkJob into a validated CleanedJob."""
        doc = raw.html_content
        sec_m = re.search(r'<section id="page"[^>]*>(.*?)</section>', doc, re.DOTALL)
        content = sec_m.group(1) if sec_m else doc

        # Title
        pos_m = re.search(r'(?:Position|Role):\s*(?:</strong>)?\s*(.*?)(?:<br\s*/?>|</p>|\r?\n)', content, re.IGNORECASE)
        title = None
        if pos_m:
            title = _strip_html(pos_m.group(1))
        if not title:
            h_m = re.search(r'<h[12][^>]*>(.*?)</h[12]>', content, re.DOTALL)
            if h_m:
                title = _strip_html(h_m.group(1))
        if not title:
            title_tag = re.search(r'<title>(.*?)</title>', doc)
            if title_tag:
                title = _strip_html(title_tag.group(1).split("|")[0].replace("jobs", "").strip())
        if not title:
            logger.debug("Dropping record without title: {}", raw.url)
            return None

        # Company / Organization
        comp_m = re.search(r'(?:Company|Organization):\s*(?:</strong>)?\s*(.*?)(?:<br\s*/?>|</p>|\r?\n)', content, re.IGNORECASE)
        company = _strip_html(comp_m.group(1)) if comp_m else None
        company = company or "Undisclosed Organization"

        # Location
        loc_m = re.search(r'Location:\s*(?:</strong>)?\s*(.*?)(?:<br\s*/?>|</p>|\r?\n)', content, re.IGNORECASE)
        location = _strip_html(loc_m.group(1)) if loc_m else None
        if location:
            if "canada" not in location.lower():
                location = f"{location}, Canada"
        else:
            location = "Canada"

        # Date posted
        dp_m = re.search(r'Date posted:\s*([A-Za-z]{3}\s+[0-9]{1,2}\s+[0-9]{4})', content)
        date_str = dp_m.group(1) if dp_m else None
        posted_at = _parse_goodwork_date(date_str)

        # Full clean description
        clean_desc = _strip_html(content) or ""
        words = len(clean_desc.split())

        # Employment type
        emp_type_code = "full_time"
        lower_desc = clean_desc.lower()
        if "part-time" in lower_desc or "part time" in lower_desc:
            emp_type_code = "part_time"
        elif "contract" in lower_desc or "temporary" in lower_desc:
            emp_type_code = "contract"
        elif "internship" in lower_desc or "intern" in lower_desc:
            emp_type_code = "internship"
        elif "volunteer" in lower_desc:
            emp_type_code = "volunteer"

        # Salary detection
        sal_min = None
        sal_max = None
        sal_disclosed = False
        pay_period = "yearly"

        sal_m = re.search(r'\$([0-9]{2,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)\s*(?:-|to)\s*\$?([0-9]{2,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)', content)
        if sal_m:
            try:
                min_f = float(sal_m.group(1).replace(",", ""))
                max_f = float(sal_m.group(2).replace(",", ""))
                if min_f > 10 and max_f > 10:
                    sal_min = min_f
                    sal_max = max_f
                    sal_disclosed = True
                    if sal_max < 200:
                        pay_period = "hourly"
            except (ValueError, TypeError):
                pass

        payload = {
            "url": raw.url,
            "job_id": raw.job_id,
            "title": title,
            "company": company,
            "location": location,
            "date_posted": date_str,
        }

        return CleanedJob(
            source_job_id=raw.job_id,
            job_title=title,
            company_name=company,
            company_logo_url=None,
            skills=[],
            location_cleaned=location,
            salary_min=sal_min,
            salary_max=sal_max,
            salary_disclosed=sal_disclosed,
            description_clean=clean_desc,
            word_count=words,
            apply_url=raw.url,
            original_url=raw.url,
            posting_date=posted_at,
            closing_date=None,
            data_quality_score=0.9 if words > 50 else 0.7,
            raw_payload=payload,
            currency_iso_code="CAD",
            pay_period=pay_period,
            employment_type_code=emp_type_code,
        )

    def parse_jobs(self, raw_jobs: list[RawGoodworkJob]) -> list[CleanedJob]:
        """Parse all raw jobs into CleanedJob records."""
        cleaned: list[CleanedJob] = []
        for r in raw_jobs:
            item = self.parse_job(r)
            if item is not None:
                cleaned.append(item)
        return cleaned
