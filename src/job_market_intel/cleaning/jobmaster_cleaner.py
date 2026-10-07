"""Cleans validated JobMaster records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawJobmasterJob`` ->
``CleanedJob``, only removing noise with no analytical value, never
making judgment calls about meaning.

JobMaster-specific notes handled here:

* **``salary_text`` is the source of truth** for what was shown. Every
  other source carries a numeric JSON blob; this one carries prose
  ("לא צוין שכר" = undisclosed, or a "₪10,000 - 12,000 לחודש"-style
  range). Only terminal cases are trusted: the undisclosed markers
  force a withhold, otherwise digit groups are extracted and paired
  as min/max (one group means a single figure shown). No assumptions
  are made about period unless a month/year word is found — an
  unknown period stays ``None`` (and the downstream salary
  standardization just can't annualize, which is honest).
* **Currency is ILS** — the platform is Israel-only and quotes ₪
  by convention. No ILS rate on the withhold list.
* **Employment label** comes in Hebrew ("משרה מלאה" = full-time,
  "משרה חלקית" = part-time); only those two map to
  ``ref.employment_types``. Everything else stays ``None`` (``כגון
  משמרות`` — shifts — has no ref code), with the raw label preserved
  in ``raw_payload``.
* **Tags** are the breadcrumb category names — site-provided, so the
  corpus already carries a consistent Hebrew vocabulary here.
* **Posting date** is estimated from the relative Hebrew text (see
  the model); the description word count / quality score conventions
  match every other cleaner. Pay period mirrors the other sources:
  ``monthly`` when the text carries no month/year word (IL postings
  are monthly by platform convention), the detected word otherwise.
"""

from __future__ import annotations

import re

from loguru import logger

from job_market_intel.scrapers.jobmaster.models import RawJobmasterJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

_EMPLOYMENT_MAP = {
    "משרה מלאה": "full_time",
    "משרה חלקית": "part_time",
}

_SALARY_HIDDEN_MARKERS = ("לא צוין", "בתיאום")


def _clean_tags(raw_tags: list[str]) -> list[str]:
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
    signals = [
        salary_disclosed,
        location_cleaned is not None,
        len(skills) > 0,
        word_count >= _SUBSTANTIAL_DESCRIPTION_WORD_COUNT,
    ]
    return round(sum(signals) / len(signals), 2)


def _map_employment_type(work_type_label: str | None) -> str | None:
    if not work_type_label:
        return None
    cleaned = clean_plain_text(work_type_label) or ""
    mapped = _EMPLOYMENT_MAP.get(cleaned.strip())
    if mapped is None and cleaned:
        logger.warning(
            "Unrecognized JobMaster employment label {!r} -- employment_type_code left None.",
            work_type_label,
        )
    return mapped


_SALARY_DIGITS_RE = re.compile(r"(\d[\d,]*)")
_MONTH_WORDS = ("לחודש", "בחודש", "חודשי", "monthly")
_YEAR_WORDS = ("לשנה", "בשנה", "שנתי", "yearly", "year")


def _extract_salary(salary_text: str | None) -> tuple[int | None, int | None, str | None]:
    """Parse "[₪X - ₪Y לחודש]"-style text.

    Returns (min, max, period). Undisclosed markers force ``(None,
    None, None)``; an unknown period stays ``None``.
    """
    if not salary_text:
        return None, None, None
    if any(marker in salary_text for marker in _SALARY_HIDDEN_MARKERS):
        return None, None, None
    found = _SALARY_DIGITS_RE.findall(salary_text)
    numbers: list[int] = []
    for token in found[:4]:
        try:
            numbers.append(int(token.replace(",", "")))
        except ValueError:
            continue
    if not numbers:
        return None, None, None
    if len(numbers) >= 2:
        low, high = sorted(numbers[:2])
    else:
        low = high = numbers[0]
    period: str | None = None
    if any(w in salary_text for w in _MONTH_WORDS):
        period = "monthly"
    elif any(w in salary_text for w in _YEAR_WORDS):
        period = "yearly"
    return low, high, period


_JOBMASTER_DEFAULT_PAY_PERIOD = "monthly"


class JobmasterCleaner:
    """Cleans a batch of validated JobMaster records into CleanedJob records."""

    def clean_job(self, raw_job: RawJobmasterJob) -> CleanedJob:
        """Clean a single validated JobMaster job record."""
        description_clean = clean_html_text(raw_job.description_html)
        location_cleaned = clean_plain_text(raw_job.location_text) or None
        skills = _clean_tags(raw_job.category_raws)
        word_count = len(description_clean.split()) if description_clean else 0

        salary_min, salary_max, pay_period = _extract_salary(raw_job.salary_text)
        if pay_period is None:
            # The pay-period slot is non-optional on CleanedJob; the
            # platform quotes monthly by convention (I1-style stance),
            # so the fallback matches every other source.
            pay_period = _JOBMASTER_DEFAULT_PAY_PERIOD
        salary_disclosed = salary_min is not None or salary_max is not None
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            salary_min, salary_max = salary_max, salary_min

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
            # Israel-only board, so ₪/ILS by convention (IL market).
            currency_iso_code="ILS",
            pay_period=pay_period,
            employment_type_code=_map_employment_type(raw_job.work_type_label),
        )

    def clean_jobs(self, raw_jobs: list[RawJobmasterJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning JobMaster job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "JobMaster cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
