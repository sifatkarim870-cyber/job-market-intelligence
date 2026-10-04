"""Cleans validated MyJob.mu records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawMyJobJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment calls
about meaning.
"""

from __future__ import annotations

import re

from loguru import logger

from job_market_intel.scrapers.myjob.models import RawMyJobJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

# "31,000 – 40,000" / "21,000 - 30,000" / "45,000" — thousands separators
# and either an en-dash or a hyphen as the range separator.
_SALARY_RANGE_RE = re.compile(r"(\d[\d,]*)\s*[–\-−]\s*(\d[\d,]*)")
_SALARY_SINGLE_RE = re.compile(r"(\d[\d,]+)")


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


def _parse_salary_range(salary_range_raw: str | None) -> tuple[int | None, int | None]:
    """Parse MyJob.mu's ``salaryRange`` string into (min, max) ints.

    Returns (None, None) for absent/unparseable input — honest absence
    rather than a guessed number.
    """
    if not salary_range_raw:
        return None, None
    match = _SALARY_RANGE_RE.search(salary_range_raw)
    if match:
        low = int(match.group(1).replace(",", ""))
        high = int(match.group(2).replace(",", ""))
        if low > high:
            low, high = high, low
        return low, high
    single = _SALARY_SINGLE_RE.search(salary_range_raw)
    if single:
        value = int(single.group(1).replace(",", ""))
        return value, value
    return None, None


_JOB_TYPE_MAP = {
    "full-time": "full_time",
    "part-time": "part_time",
    "fixed-term contract (cdd)": "contract",
    "temporary": "temporary",
    "internship": "internship",
    "freelance": "freelance",
}


def _map_employment_type(job_type_raw: str | None) -> str | None:
    """Map MyJob.mu's ``jobType`` onto ref.employment_types.code.

    MyJob.mu's vocabulary is already English and maps 1:1 onto the
    reference codes (all six observed values have a target); unknown
    values still fall through to ``None`` rather than being guessed at.
    """
    if not job_type_raw:
        return None
    normalized = job_type_raw.strip().lower()
    mapped = _JOB_TYPE_MAP.get(normalized)
    if mapped is None:
        for key, value in _JOB_TYPE_MAP.items():
            if key in normalized:
                return value
        logger.warning(
            "Unrecognized MyJob.mu jobType {!r} -- employment_type_code "
            "left None; the real value is still preserved in raw_payload.",
            job_type_raw,
        )
        return None
    return mapped


class MyJobCleaner:
    """Cleans a batch of validated MyJob.mu records into CleanedJob records."""

    def clean_job(self, raw_job: RawMyJobJob) -> CleanedJob:
        """Clean a single validated MyJob.mu job record."""
        description_clean = clean_html_text(raw_job.description_raw)
        location_cleaned = clean_plain_text(raw_job.location_raw)
        skills = _clean_tags(raw_job.tags)
        word_count = len(description_clean.split()) if description_clean else 0

        # showSalary=false means the board displays "Salary not
        # disclosed" even though a range exists in the payload — the
        # site is deliberately withholding it, so record honest absence.
        if raw_job.show_salary:
            salary_min, salary_max = _parse_salary_range(raw_job.salary_range_raw)
        else:
            salary_min, salary_max = None, None
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
            # Mauritius posts salaries in MUR, monthly (the observed
            # ranges — e.g. "31,000 - 40,000" for a full-time role —
            # are monthly figures; annual would be implausibly low).
            currency_iso_code="MUR",
            pay_period="monthly",
            employment_type_code=_map_employment_type(raw_job.contract_type_raw),
        )

    def clean_jobs(self, raw_jobs: list[RawMyJobJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning MyJob.mu job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "MyJob.mu cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
