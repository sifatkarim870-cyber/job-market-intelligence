"""Parser and normalizer for JobBKK (Thailand) postings."""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from .models import RawJobbkkJob

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


def _parse_iso_date(dt_str: str | None) -> datetime | None:
    """Parse ISO date/datetime strings."""
    if not dt_str:
        return None
    clean = dt_str.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(clean)
    except Exception:
        return None


class JobbkkParser:
    """Transforms RawJobbkkJob instances into CleanedJob records."""

    def parse_job(self, raw: RawJobbkkJob) -> CleanedJob | None:
        """Parse a single RawJobbkkJob into a validated CleanedJob."""
        ld = raw.json_ld
        if not ld:
            return None

        title = (ld.get("title") or "").strip()
        if not title and raw.html_title:
            title = raw.html_title.split("|")[0].strip()
        if not title:
            logger.debug("Dropping record without title: {}", raw.url)
            return None

        org = ld.get("hiringOrganization") or {}
        company = (org.get("name") or "Confidential / Undisclosed").strip()
        logo_url = org.get("logo")

        # Location
        loc_obj = ld.get("jobLocation") or {}
        addr = loc_obj.get("address") or {}
        loc_parts: list[str] = []
        if isinstance(addr, dict):
            for k in ("streetAddress", "addressLocality", "addressRegion"):
                v = addr.get(k)
                if v and str(v).strip():
                    loc_parts.append(str(v).strip())
        loc_clean = ", ".join(loc_parts)
        if loc_clean:
            if "thailand" not in loc_clean.lower():
                loc_clean = f"{loc_clean}, Thailand"
        else:
            loc_clean = "Thailand"

        # Description
        desc_text = _strip_html(ld.get("description")) or ""
        cat = ld.get("occupationalCategory")
        body_parts = [title, f"Company: {company}"]
        if cat:
            body_parts.append(f"Category: {cat}")
        if desc_text:
            body_parts.append(desc_text)
        full_desc = "\n\n".join(body_parts).strip()
        words = len(full_desc.split())

        # Salary
        sal_min = None
        sal_max = None
        sal_disclosed = False
        pay_period = "monthly"
        base_sal = ld.get("baseSalary")
        if isinstance(base_sal, dict):
            val_obj = base_sal.get("value")
            if isinstance(val_obj, dict):
                min_v = val_obj.get("minValue")
                max_v = val_obj.get("maxValue")
                if min_v is not None:
                    try:
                        sal_min = float(min_v)
                    except (ValueError, TypeError):
                        pass
                if max_v is not None:
                    try:
                        sal_max = float(max_v)
                    except (ValueError, TypeError):
                        pass
                if sal_min or sal_max:
                    sal_disclosed = True

                unit = (val_obj.get("unitText") or "").upper()
                if "MONTH" in unit:
                    pay_period = "monthly"
                elif "YEAR" in unit:
                    pay_period = "yearly"
                elif "HOUR" in unit:
                    pay_period = "hourly"

        # Employment type
        emp_type_str = str(ld.get("employmentType") or "").upper()
        emp_type_code = "full_time"
        if "PART" in emp_type_str:
            emp_type_code = "part_time"
        elif "CONTRACT" in emp_type_str or "TEMPORARY" in emp_type_str:
            emp_type_code = "contract"
        elif "INTERN" in emp_type_str:
            emp_type_code = "internship"

        # Dates
        posted_at = _parse_iso_date(ld.get("datePosted"))
        closing_date = _parse_iso_date(ld.get("validThrough"))

        skills: list[str] = []
        if cat:
            skills.extend([s.strip() for s in cat.split("/") if s.strip()])

        return CleanedJob(
            source_job_id=raw.job_id,
            job_title=title,
            company_name=company,
            company_logo_url=logo_url,
            skills=skills,
            location_cleaned=loc_clean,
            salary_min=sal_min,
            salary_max=sal_max,
            salary_disclosed=sal_disclosed,
            description_clean=full_desc,
            word_count=words,
            apply_url=raw.url,
            original_url=raw.url,
            posting_date=posted_at,
            closing_date=closing_date,
            data_quality_score=0.9 if words > 30 else 0.7,
            raw_payload=ld,
            currency_iso_code="THB",
            pay_period=pay_period,
            employment_type_code=emp_type_code,
        )

    def parse_jobs(self, raw_jobs: list[RawJobbkkJob]) -> list[CleanedJob]:
        """Parse a list of raw jobs into CleanedJob records."""
        cleaned: list[CleanedJob] = []
        for r in raw_jobs:
            item = self.parse_job(r)
            if item is not None:
                cleaned.append(item)
        return cleaned
