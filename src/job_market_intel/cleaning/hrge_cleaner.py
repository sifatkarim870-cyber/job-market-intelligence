"""Cleans validated HR.ge records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawHRGeJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment
calls about meaning.

Two HR.ge-specific quirks handled here:

* **Georgian-only announcements served under ``Accept-Language: en``**
  come back as the original Georgian text behind a short English notice
  ("This announcement is available only in Georgian Language, please
  see the text below …"). That notice is boilerplate, not job content,
  so it is stripped before word counting; the Georgian body itself is
  left alone for the translation layer to handle downstream.
* **Employment mapping prefers the schedule enum** (``workScheduleRaw``
  "Full-time"/"Part-time" → ``full_time``/``part_time``, matching what
  other sources store in ``employment_type_code``) and falls back to the
  contract-kind enum (``employmentTypeName`` "Fixed-term contract" →
  ``contract``). Unmapped values fall through to ``None`` — honest
  absence rather than a guess; both raw values stay in ``raw_payload``.
"""

from __future__ import annotations

import re

from loguru import logger

from job_market_intel.scrapers.hrge.models import RawHRGeJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

# "This announcement is available only in Georgian Language, please see
# the text below (You can also switch the site Language from header
# language switcher)" — the site's notice when a posting has no English
# body. Generalized over the language name in case other notices exist.
_GEO_NOTICES_RE = re.compile(
    r"^\s*This announcement is available only in [A-Za-z]+ Language,?\s*"
    r"please see the text below\.?\s*(\([^)]*\))?\s*",
    re.IGNORECASE,
)


def _clean_tags(raw_tags: list[str]) -> list[str]:
    """Clean, lowercase, and de-duplicate raw tags, preserving first-seen order."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw_tag in raw_tags:
        cleaned_tag = clean_plain_text(raw_tag)
        if not cleaned_tag:
            continue
        normalized = cleaned_tag.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return cleaned


def _compute_data_quality_score(
    *,
    salary_disclosed: bool,
    location_cleaned: str | None,
    skills: list[str],
    word_count: int,
) -> float:
    """Same four-signal, equally-weighted formula every other cleaner uses."""
    signals = [
        salary_disclosed,
        location_cleaned is not None,
        len(skills) > 0,
        word_count >= _SUBSTANTIAL_DESCRIPTION_WORD_COUNT,
    ]
    return round(sum(signals) / len(signals), 2)


def _strip_language_notice(description: str) -> str:
    """Remove the site's "available only in … Language" boilerplate prefix."""
    return _GEO_NOTICES_RE.sub("", description, count=1).strip()


# English enums as served with Accept-Language: en (confirmed live).
_SCHEDULE_MAP = {
    "full-time": "full_time",
    "part-time": "part_time",
}
_CONTRACT_MAP = {
    "fixed-term contract": "contract",
    "fixed term contract": "contract",
    "temporary": "temporary",
    "internship": "internship",
    "apprenticeship": "apprenticeship",
    "freelance": "freelance",
}


def _map_employment_type(work_schedule_raw: str | None, contract_type_raw: str | None) -> str | None:
    """Map HR.ge's enums onto ref.employment_types.code.

    Schedule wins ("Full-time" → ``full_time``) because it is the
    dimension other sources store there; the contract-kind enum is the
    fallback for rows whose schedule is unrecognized. Unknown values
    fall through to ``None`` rather than being guessed at.
    """
    for value, table in (
        (work_schedule_raw, _SCHEDULE_MAP),
        (contract_type_raw, _CONTRACT_MAP),
    ):
        if not value:
            continue
        normalized = value.strip().lower()
        mapped = table.get(normalized)
        if mapped is None:
            for key, code in table.items():
                if key in normalized:
                    return code
        else:
            return mapped
    if work_schedule_raw or contract_type_raw:
        logger.warning(
            "Unrecognized HR.ge schedule/type ({!r} / {!r}) -- "
            "employment_type_code left None; the raw values are still "
            "preserved in raw_payload.",
            work_schedule_raw,
            contract_type_raw,
        )
    return None


class HRGeCleaner:
    """Cleans a batch of validated HR.ge records into CleanedJob records."""

    def clean_job(self, raw_job: RawHRGeJob) -> CleanedJob:
        """Clean a single validated HR.ge job record."""
        description_clean = clean_html_text(raw_job.description_raw)
        if description_clean:
            description_clean = _strip_language_notice(description_clean)
        location_cleaned = clean_plain_text(raw_job.location_raw)
        skills = _clean_tags(raw_job.tags)
        word_count = len(description_clean.split()) if description_clean else 0

        # Disclosure flags: observed pairing is amounts + showSalary=true
        # for disclosed rows; showSalary=false (or hideSalary=true) means
        # the board deliberately withholds the figure even if present.
        if raw_job.show_salary is False or raw_job.hide_salary is True:
            salary_min, salary_max = None, None
        else:
            salary_min, salary_max = raw_job.salary_from_raw, raw_job.salary_to_raw
        salary_disclosed = salary_min is not None or salary_max is not None

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=clean_plain_text(raw_job.job_title) or raw_job.job_title,
            company_name=clean_plain_text(raw_job.company_name) or raw_job.company_name,
            company_logo_url=raw_job.company_logo_url,
            skills=skills,
            location_cleaned=location_cleaned,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=description_clean,
            word_count=word_count,
            apply_url=raw_job.original_url,
            original_url=raw_job.original_url,
            posting_date=raw_job.posting_date,
            closing_date=raw_job.closing_date,
            data_quality_score=_compute_data_quality_score(
                salary_disclosed=salary_disclosed,
                location_cleaned=location_cleaned,
                skills=skills,
                word_count=word_count,
            ),
            raw_payload=raw_job.raw_payload,
            # Georgia posts salaries in GEL, monthly (observed ranges —
            # e.g. salaryFrom=1200 for a Tbilisi cashier — are monthly
            # figures; hourly would be implausibly high, annual low).
            currency_iso_code="GEL",
            pay_period="monthly",
            employment_type_code=_map_employment_type(
                raw_job.work_schedule_raw, raw_job.contract_type_raw
            ),
        )

    def clean_jobs(self, raw_jobs: list[RawHRGeJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning HR.ge job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "HR.ge cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
