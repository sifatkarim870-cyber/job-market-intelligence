"""Parser and normalizer for Ajira Portal Tanzania vacancies."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from job_market_intel.cleaning.common import CleanedJob
from .exceptions import AjiraTzParseError
from .models import RawAjiraTzJob

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str | None) -> str | None:
    """Remove HTML tags, decode entities, and normalize whitespace."""
    if not html:
        return None
    text = _TAG_RE.sub(" ", html)
    text = re.sub(r"[ \t]+", " ", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text or None


def _parse_iso_date(dt_str: str | None) -> datetime | None:
    """Parse ISO dates like '2026-11-26T00:00' or '2026-11-26T00:00:00'."""
    if not dt_str:
        return None
    clean = dt_str.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(clean)
    except Exception:
        return None


class AjiraTzParser:
    """Parses raw Ajira TZ GraphQL items into CleanedJob records."""

    def parse_job(
        self,
        listing: dict[str, Any],
        detail: dict[str, Any] | None = None,
    ) -> CleanedJob | None:
        """Merge listing and detail into a CleanedJob."""
        if not listing:
            return None

        combined = {**listing, **(detail or {})}
        vacancy_id = combined.get("id")
        if not vacancy_id:
            return None

        scheme: dict[str, Any] = combined.get("scheme") or {}
        salary_scale: dict[str, Any] = scheme.get("salaryScale") or {}
        employer: dict[str, Any] = scheme.get("emp") or {}

        title = (scheme.get("codeNo") or "").strip()
        if not title:
            title = f"Public Service Vacancy #{vacancy_id}"

        emp_name = (employer.get("name") or "").strip() or "Public Service Recruitment Secretariat (PSRS)"

        duties_text = _strip_html(scheme.get("dutiesResponsibilities"))
        qual_text = _strip_html(scheme.get("qualifications"))
        salary_name = (salary_scale.get("name") or "").strip()
        no_of_post = combined.get("noOfPost")

        desc_parts: list[str] = [title, f"Employer: {emp_name}"]
        if salary_name:
            desc_parts.append(f"Salary Scale: {salary_name}")
        if no_of_post:
            desc_parts.append(f"Number of Posts: {no_of_post}")
        if duties_text:
            desc_parts.append(f"Duties & Responsibilities:\n{duties_text}")
        if qual_text:
            desc_parts.append(f"Qualifications & Experience:\n{qual_text}")

        desc_clean = "\n\n".join(desc_parts)
        words = len(desc_clean.split())

        loc = f"{emp_name}, Tanzania" if "Tanzania" not in emp_name else emp_name

        orig_url = f"https://portal.ajira.go.tz/advert/display_advert/{vacancy_id}"
        apply_url = orig_url

        open_dt = _parse_iso_date(combined.get("openDate"))
        close_dt = _parse_iso_date(combined.get("closeDate"))

        return CleanedJob(
            source_job_id=str(vacancy_id),
            job_title=title,
            company_name=emp_name,
            company_logo_url=None,
            skills=[],
            location_cleaned=loc,
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=desc_clean,
            word_count=words,
            apply_url=apply_url,
            original_url=orig_url,
            posting_date=open_dt,
            closing_date=close_dt,
            data_quality_score=0.9 if words > 50 else 0.7,
            raw_payload=combined,
            currency_iso_code="TZS",
            pay_period="monthly",
            employment_type_code="full_time",
            work_schedule=None,
        )

    def parse_jobs(
        self,
        listings: list[dict[str, Any]],
        details_map: dict[int, dict[str, Any]],
    ) -> list[CleanedJob]:
        """Parse all vacancies using the fetched details."""
        cleaned: list[CleanedJob] = []
        for item in listings:
            vid = item.get("id")
            detail = details_map.get(vid) if vid else None
            try:
                job = self.parse_job(item, detail)
                if job:
                    cleaned.append(job)
            except Exception as exc:
                logger.warning("Failed to parse vacancy %s: %s", vid, exc)
        return cleaned
