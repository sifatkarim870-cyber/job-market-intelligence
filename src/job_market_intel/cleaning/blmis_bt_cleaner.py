"""Cleans validated BLMIS records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawBlmisJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment calls
about meaning.

BLMIS-specific quirks handled here:

* **Salary is a single monthly figure.** ``starting_salary`` is quoted once
  with no upper bound and no currency code; the cleaner keeps it as the
  lower bound and leaves the upper bound unstated rather than inventing
  one, drops a non-positive value, and treats an absent/zero figure as
  undisclosed. A figure of ``1`` is also treated as undisclosed: the board
  uses it as the "not stated" placeholder (measured on a 2026-11-21
  "sales manager" post whose body says only "Regular job as sales
  manager"), and a monthly ngultrum salary of one is not a salary. Same
  "a placeholder is not a salary" rule as ``jobwebghana_cleaner``.
  Currency is ``BTN`` (ngultrum) for domestic postings; the handful of
  overseas postings quote the destination's currency, mapped from the
  ``placement`` country name with a ``BTN`` fallback.
* **Employment type is prose.** ``employment_type`` is "Regular",
  "Contract" or "Intern"; the recognized labels are mapped onto
  ``ref.employment_types``. The rare combined label "Casual/Freelance" is
  deliberately left unmapped: it names two different engagement types at
  once, so picking either ``temporary`` or ``freelance`` would be a guess.
  The raw value stays in ``raw_payload`` and a warning is logged.
* **There is no skills or work-mode field**, so ``skills`` stays empty and
  ``remote_work_type_code`` stays ``None`` -- an honest absence, not a
  guess.
* **Descriptions are several prose blobs** (``job_description`` plus
  ``qualification``, ``eligible_criteria``, ``terms_conditon`` and
  ``remarks``); all are folded into one cleaned description, since each is
  job content with no separate ``CleanedJob`` slot.
"""

from __future__ import annotations

import re

from loguru import logger

from job_market_intel.scrapers.blmis_bt.models import RawBlmisJob

from .common import CleanedJob
from .text_utils import clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

#: ``employment_type`` -> ref.employment_types.code.
_EMPLOYMENT_MAP = {
    "regular": "full_time",
    "permanent": "full_time",
    "full time": "full_time",
    "fulltime": "full_time",
    "part time": "part_time",
    "parttime": "part_time",
    "part-time": "part_time",
    "contract": "contract",
    "contractual": "contract",
    "contract based": "contract",
    "temporary": "temporary",
    "temp": "temporary",
    "internship": "internship",
    "intern": "internship",
    "freelance": "freelance",
    "apprenticeship": "apprenticeship",
    "apprentice": "apprenticeship",
}

#: Overseas postings quote their salary in the destination's currency, which
#: the payload never states. This maps the ``placement`` country name (case
#: insensitive) onto its ISO 4217 code; anything unmapped falls back to the
#: portal's home currency BTN. Only Qatar had appeared at scoping.
_OVERSEA_CURRENCY = {
    "qatar": "QAR",
    "united arab emirates": "AED",
    "uae": "AED",
    "saudi arabia": "SAR",
    "kuwait": "KWD",
    "bahrain": "BHD",
    "oman": "OMR",
}

_DEFAULT_CURRENCY = "BTN"


def _normalize(value: str) -> str:
    """Lowercase, hyphens/slashes/underscores -> spaces, collapse runs."""
    lowered = value.strip().lower().replace("-", " ").replace("/", " ").replace("_", " ")
    return re.sub(r"\s+", " ", lowered).strip()


def map_employment_type(raw: str | None) -> str | None:
    """Map the record's ``employment_type`` onto ref.employment_types.code."""
    if not raw:
        return None
    mapped = _EMPLOYMENT_MAP.get(_normalize(raw))
    if mapped is None:
        logger.warning(
            "Unrecognized BLMIS employment type {!r} -- employment_type_code "
            "left None; the raw value is preserved in raw_payload.",
            raw,
        )
    return mapped


def map_oversea_currency(country_text: str | None) -> str:
    """Map an overseas posting's destination country onto an ISO 4217 code."""
    if country_text:
        mapped = _OVERSEA_CURRENCY.get(_normalize(country_text))
        if mapped is not None:
            return mapped
    return _DEFAULT_CURRENCY


#: The board writes this instead of a salary when the employer did not state
#: one. A monthly ngultrum salary of one is not a salary, so it is read as
#: undisclosed (the same rule ``jobwebghana_cleaner`` applies to that board's
#: own default).
_PLACEHOLDER_SALARY_MAX = 1.0


def _stated_salary(value: float | None) -> float | None:
    """A usable monthly figure passes through; anything below the board's
    placeholder (0, negative, or exactly 1) means "unstated" -> None."""
    if value is None:
        return None
    number = float(value)
    if number <= _PLACEHOLDER_SALARY_MAX:
        return None
    return number


def _compose_description(raw_job: RawBlmisJob) -> str | None:
    """Fold the board's several prose blobs into one cleaned description."""
    parts = [
        clean_plain_text(part)
        for part in (
            raw_job.description_raw,
            raw_job.qualification_raw,
            raw_job.eligibility_raw,
            raw_job.terms_raw,
            raw_job.remarks_raw,
        )
    ]
    joined = "\n\n".join(part for part in parts if part)
    return clean_plain_text(joined) or None


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


class BlmisCleaner:
    """Cleans a batch of validated BLMIS records into CleanedJob records."""

    def clean_job(self, raw_job: RawBlmisJob) -> CleanedJob:
        """Clean a single validated BLMIS job record."""
        description_clean = _compose_description(raw_job)
        location_cleaned = clean_plain_text(raw_job.location_text) or None
        skills: list[str] = []
        word_count = len(description_clean.split()) if description_clean else 0

        salary_min = _stated_salary(raw_job.salary_min_raw)
        # ``starting_salary`` is a single figure; the upper bound is genuinely
        # unstated, so it is left None rather than mirrored from the lower one.
        salary_max = None
        salary_disclosed = salary_min is not None

        currency_iso_code = (
            map_oversea_currency(raw_job.country_text) if raw_job.is_oversea else _DEFAULT_CURRENCY
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=clean_plain_text(raw_job.job_title) or raw_job.job_title,
            company_name=clean_plain_text(raw_job.company_name) or raw_job.company_name,
            company_logo_url=None,
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
            # Bhutan quotes a monthly starting salary in ngultrum (BTN), unless
            # the posting is overseas (module docstring).
            currency_iso_code=currency_iso_code,
            pay_period="monthly",
            employment_type_code=map_employment_type(raw_job.employment_type_raw),
            remote_work_type_code=None,
        )

    def clean_jobs(self, raw_jobs: list[RawBlmisJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning BLMIS job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "BLMIS cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
