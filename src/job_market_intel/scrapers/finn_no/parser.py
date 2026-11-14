"""Parser and normalizer for FINN.no (Norway)."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from job_market_intel.cleaning.common import CleanedJob
from .exceptions import FinnNoParseError
from .models import RawFinnNoJob

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str | None) -> str:
    """Remove HTML tags, decode entities, and normalize whitespace."""
    if not html:
        return ""
    text = _TAG_RE.sub(" ", html)
    text = re.sub(r"[ \t]+", " ", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _parse_date(dt_str: str | None) -> datetime | None:
    """Parse ISO date strings."""
    if not dt_str:
        return None
    clean = dt_str.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(clean)
    except Exception:
        return None


class FinnNoParser:
    """Parses RawFinnNoJob models into CleanedJob records."""

    def parse_job(self, job: RawFinnNoJob) -> CleanedJob | None:
        """Transform a single RawFinnNoJob into CleanedJob."""
        data = job.json_ld
        if not data:
            return None

        title = (data.get("title") or "").strip()
        if not title:
            return None

        # Hiring Organization
        hiring_org = data.get("hiringOrganization") or {}
        if isinstance(hiring_org, dict):
            company_name = (hiring_org.get("name") or "").strip()
            logo_url = hiring_org.get("logo")
        elif isinstance(hiring_org, str):
            company_name = hiring_org.strip()
            logo_url = None
        else:
            company_name = "FINN.no Employer"
            logo_url = None

        if not company_name:
            company_name = "FINN.no Employer"

        # Location
        loc_parts: list[str] = []
        job_loc = data.get("jobLocation") or {}
        if isinstance(job_loc, dict):
            addr = job_loc.get("address") or {}
            if isinstance(addr, dict):
                locality = (addr.get("addressLocality") or "").strip()
                region = (addr.get("addressRegion") or "").strip()
                if locality:
                    loc_parts.append(locality)
                elif region:
                    loc_parts.append(region)
            elif isinstance(addr, str) and addr.strip():
                loc_parts.append(addr.strip())

        loc_parts.append("Norway")
        location_cleaned = ", ".join(loc_parts)

        # Description
        desc_raw = data.get("description") or ""
        desc_clean = _strip_html(desc_raw)
        if not desc_clean:
            desc_clean = f"{title}\n\nEmployer: {company_name}\nLocation: {location_cleaned}"

        word_count = len(desc_clean.split())

        # Dates
        post_dt = _parse_date(data.get("datePosted"))
        valid_dt = _parse_date(data.get("validThrough"))

        # Employment type
        emp_type_raw = str(data.get("employmentType") or "").lower()
        if "part" in emp_type_raw or "deltid" in emp_type_raw:
            emp_type = "part_time"
        elif "contract" in emp_type_raw or "vikariat" in emp_type_raw or "prosjekt" in emp_type_raw:
            emp_type = "contract"
        else:
            emp_type = "full_time"

        # Salary
        sal_min = None
        sal_max = None
        sal_disclosed = False
        base_sal = data.get("baseSalary")
        if isinstance(base_sal, dict):
            val = base_sal.get("value")
            if isinstance(val, dict):
                sal_min = val.get("minValue") or val.get("value")
                sal_max = val.get("maxValue") or val.get("value")
                sal_disclosed = sal_min is not None or sal_max is not None

        return CleanedJob(
            source_job_id=job.job_id,
            job_title=title,
            company_name=company_name,
            company_logo_url=str(logo_url) if logo_url else None,
            skills=[],
            location_cleaned=location_cleaned,
            salary_min=float(sal_min) if sal_min is not None else None,
            salary_max=float(sal_max) if sal_max is not None else None,
            salary_disclosed=sal_disclosed,
            description_clean=desc_clean,
            word_count=word_count,
            apply_url=job.url,
            original_url=job.url,
            posting_date=post_dt,
            closing_date=valid_dt,
            data_quality_score=0.9 if word_count > 50 else 0.7,
            raw_payload=data,
            currency_iso_code="NOK",
            pay_period="monthly",
            employment_type_code=emp_type,
            work_schedule=None,
        )

    def parse_jobs(self, raw_jobs: list[RawFinnNoJob]) -> list[CleanedJob]:
        """Parse multiple RawFinnNoJob models into CleanedJob list."""
        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                job = self.parse_job(raw)
                if job:
                    cleaned.append(job)
            except Exception as exc:
                logger.warning("Failed to parse FINN.no job %s: %s", raw.job_id, exc)
        return cleaned
