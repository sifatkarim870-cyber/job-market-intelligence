"""Parser and normalizer for ADEM (Luxembourg) raw jobs."""

from __future__ import annotations

from typing import Any

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from .models import RawAdemLuJob


class AdemLuParser:
    """Parses raw ADEM dicts and transforms them into CleanedJob records."""

    def parse_job(self, record: dict[str, Any]) -> CleanedJob | None:
        """Parse a single raw ADEM record into a validated CleanedJob."""
        ref = str(record.get("ref", "")).strip()
        title = (record.get("title") or "").strip()
        if not ref or not title:
            logger.debug("Dropping record without ref or title: {}", record)
            return None

        employer = (record.get("employer") or "").strip() or "ADEM Postings"
        commune = record.get("commune") or record.get("canton") or "Luxembourg"
        loc = f"{commune.strip()}, Luxembourg"

        desc = record.get("description_text") or ""
        if not desc:
            parts = [
                title,
                f"Employer: {employer}",
                f"Domain: {record.get('domain') or 'General'}",
                f"Role: {record.get('job') or title}",
                f"Contract: {record.get('contract') or 'Standard'} ({record.get('duration') or 'N/A'})",
            ]
            if record.get("languages"):
                parts.append(f"Languages: {', '.join(record['languages'])}")
            if record.get("skills"):
                parts.append(f"Skills: {', '.join(record['skills'])}")
            desc = "\n\n".join(parts)

        emp_type = "full_time"
        dur = (record.get("duration") or "").upper()
        time_str = (record.get("time") or "").lower()
        contract_str = (record.get("contract") or "").lower()
        if "CDD" in dur or "intérimaire" in contract_str or "temporaire" in contract_str:
            emp_type = "contract"
        elif "partiel" in time_str:
            emp_type = "part_time"

        orig_url = f"https://adem.public.lu/en/jobboard/offre.html?ref={ref}"
        apply_url = record.get("apply_url") or orig_url
        words = len(desc.split())

        skills_list = list(record.get("skills") or [])
        for lang in record.get("languages") or []:
            if lang and lang not in skills_list:
                skills_list.append(lang)

        return CleanedJob(
            source_job_id=ref,
            job_title=title,
            company_name=employer,
            company_logo_url=None,
            skills=skills_list,
            location_cleaned=loc,
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=desc,
            word_count=words,
            apply_url=apply_url,
            original_url=orig_url,
            posting_date=None,
            closing_date=None,
            data_quality_score=0.9 if words > 50 else 0.7,
            raw_payload=record,
            currency_iso_code="EUR",
            pay_period="monthly",
            employment_type_code=emp_type,
            work_schedule=record.get("time"),
        )

    def parse_jobs(self, records: list[dict[str, Any]]) -> list[CleanedJob]:
        """Parse a collection of raw records, discarding invalid ones."""
        cleaned: list[CleanedJob] = []
        for rec in records:
            job = self.parse_job(rec)
            if job is not None:
                cleaned.append(job)
        return cleaned
