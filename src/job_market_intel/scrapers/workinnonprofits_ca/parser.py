"""Parser and normalizer for WorkInNonProfits (Canada) postings."""

from __future__ import annotations

import html
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from .models import RawWorkInNonProfitsJob

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


def _parse_deadline_date(date_str: str | None) -> datetime | None:
    """Parse dates like 'Thursday, 26 November 2026' or '26 Nov 2026'."""
    if not date_str:
        return None
    clean = re.sub(r"^[A-Za-z]+,\s*", "", date_str.strip())
    clean = clean.replace(",", "").strip()
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            pass
    return None


def _parse_pub_date(pub_date_str: str | None) -> datetime | None:
    """Parse RFC 822 / 2822 dates like 'Sat, 14 Nov 2026 21:15:02 +0000'."""
    if not pub_date_str:
        return None
    try:
        dt = parsedate_to_datetime(pub_date_str)
        return dt.replace(tzinfo=None)
    except Exception:
        pass
    return None


class WorkInNonProfitsParser:
    """Transforms RawWorkInNonProfitsJob instances into CleanedJob records."""

    def parse_job(self, raw: RawWorkInNonProfitsJob) -> CleanedJob | None:
        """Parse a single RawWorkInNonProfitsJob into a validated CleanedJob."""
        item = raw.item
        title = item.title
        if not title:
            logger.debug("Dropping record without title: {}", item.url)
            return None

        employer = item.employer or "Undisclosed Organization"
        location = item.location or "Canada"
        if "canada" not in location.lower():
            location = f"{location}, Canada"

        # Extract text from detail page
        soup = BeautifulSoup(raw.html_content, "html.parser")
        central = soup.find("div", id="central_content")
        if central:
            for bad in central.find_all(["script", "style", "modal", "nav", "form"]):
                bad.decompose()
            for modal in central.find_all("div", class_="modal"):
                modal.decompose()
            for share in central.find_all("div", id="share_options"):
                share.decompose()
            desc_text = central.get_text("\n", strip=True)
        else:
            for bad in soup.find_all(["script", "style", "nav", "header", "footer"]):
                bad.decompose()
            desc_text = soup.get_text("\n", strip=True)

        desc_text = re.sub(r"\n{3,}", "\n\n", desc_text).strip()
        words = len(desc_text.split())

        # Dates
        posted_at = _parse_pub_date(item.pub_date)
        closing_at = _parse_deadline_date(item.deadline)

        # Salary & compensation
        sal_min = None
        sal_max = None
        sal_disclosed = False
        pay_period = "yearly"

        # Check type_info and full text for salary
        search_blob = f"{item.type_info or ''} {desc_text}"
        sal_m = re.search(
            r"\$([0-9]{2,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)\s*(?:-|to)\s*\$?([0-9]{2,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)",
            search_blob,
        )
        if sal_m:
            try:
                min_f = float(sal_m.group(1).replace(",", ""))
                max_f = float(sal_m.group(2).replace(",", ""))
                if min_f > 10 and max_f > 10:
                    sal_min = min_f
                    sal_max = max_f
                    sal_disclosed = True
                    if sal_max < 250 or "/hr" in search_blob.lower():
                        pay_period = "hourly"
            except (ValueError, TypeError):
                pass
        else:
            single_m = re.search(r"\$([0-9]{2,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)\s*(?:/hr|an hour|per hour)", search_blob, re.IGNORECASE)
            if single_m:
                try:
                    val = float(single_m.group(1).replace(",", ""))
                    if val > 10:
                        sal_min = val
                        sal_max = val
                        sal_disclosed = True
                        pay_period = "hourly"
                except (ValueError, TypeError):
                    pass

        # Employment type
        emp_type_code = "full_time"
        lower_type = (item.type_info or "").lower()
        lower_desc = desc_text.lower()
        combo = f"{lower_type} {lower_desc[:500]}"

        if "part-time" in combo or "part time" in combo:
            emp_type_code = "part_time"
        elif "contract" in combo or "temporary" in combo:
            emp_type_code = "contract"
        elif "internship" in combo or "intern" in combo:
            emp_type_code = "internship"
        elif "volunteer" in combo:
            emp_type_code = "volunteer"
        elif "casual" in combo or "relief" in combo:
            emp_type_code = "part_time"

        payload = {
            "url": item.url,
            "job_id": item.job_id,
            "title": title,
            "employer": employer,
            "location": location,
            "type_info": item.type_info,
            "deadline": item.deadline,
            "pub_date": item.pub_date,
        }

        return CleanedJob(
            source_job_id=item.job_id,
            job_title=title,
            company_name=employer,
            company_logo_url=None,
            skills=[],
            location_cleaned=location,
            salary_min=sal_min,
            salary_max=sal_max,
            salary_disclosed=sal_disclosed,
            description_clean=desc_text,
            word_count=words,
            apply_url=item.url,
            original_url=item.url,
            posting_date=posted_at,
            closing_date=closing_at,
            data_quality_score=0.95 if words > 60 else 0.7,
            raw_payload=payload,
            currency_iso_code="CAD",
            pay_period=pay_period,
            employment_type_code=emp_type_code,
        )

    def parse_jobs(self, raw_jobs: list[RawWorkInNonProfitsJob]) -> list[CleanedJob]:
        """Parse all raw jobs into CleanedJob records."""
        cleaned: list[CleanedJob] = []
        for r in raw_jobs:
            item = self.parse_job(r)
            if item is not None:
                cleaned.append(item)
        return cleaned
