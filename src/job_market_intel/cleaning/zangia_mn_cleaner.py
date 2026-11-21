"""Cleans validated Zangia records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawZangiaJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment calls
about meaning.

Zangia-specific quirks handled here:

* **Salary is always stated.** Every sampled row carried a populated
  ``salary`` object in whole Mongolian tugrik (MNT), quoted monthly by the
  board's own convention. The cleaner drops a non-positive bound and
  swaps a reversed pair rather than dropping it.
* **Currency is MNT**, the Mongolian tugrik, and ``pay_period`` is
  ``monthly`` (Zangia quotes a monthly wage, matching Mongolian
  convention and the ``top-professions`` endpoint's own min/max figures).
* **Employment type** comes from the detail's ``timetype.name_en``;
  observed values are ``"Full-time"`` and ``"Shift"``. ``Full-time`` maps
  onto ``ref.employment_types``; ``"Shift"`` is a work *schedule*, not an
  employment type, so it is silently ignored rather than mis-mapped (the
  raw value stays in ``raw_payload``).
* **Descriptions are three HTML blobs** (``description``,
  ``requirements``, ``additional``); all are job content with no separate
  ``CleanedJob`` slot, so they are folded into one cleaned description.
* **No remote signal.** Zangia publishes a district ``location`` and no
  work-mode field, so ``remote_work_type_code`` is left None rather than
  guessed (the TopJobs/TimesJobs stance).

Skills are the board's own ``skills`` list (English names preferred);
``branch``, ``jobLevel``, ``address`` and the numeric ``id`` have no
matching ``CleanedJob`` slot here, so they stay in ``raw_payload`` only.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.zangia_mn.models import RawZangiaJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

#: ``timetype.name_en`` -> ref.employment_types.code. Observed live:
#: "Full-time" and "Shift". "Part-time"/"Contract"/... included defensively.
_EMPLOYMENT_MAP = {
    "full_time": "full_time",
    "full-time": "full_time",
    "part_time": "part_time",
    "part-time": "part_time",
    "contract": "contract",
    "contractual": "contract",
    "temporary": "temporary",
    "internship": "internship",
    "freelance": "freelance",
    "apprenticeship": "apprenticeship",
    "permanent": "full_time",
}

#: Known ``timetype`` values that are work *schedules*, not employment
#: types; recognized only so they are ignored without a spurious warning.
_NON_EMPLOYMENT_TOKENS = {"shift", "rotating_shift", "shift_work"}


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


def _normalize(value: str) -> str:
    """Lowercase, hyphens/spaces -> underscores, for map lookups."""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _map_employment_type(raw: str | None) -> str | None:
    """Map the detail's ``timetype.name_en`` onto ref.employment_types.code."""
    if not raw:
        return None
    key = _normalize(raw)
    if key in _NON_EMPLOYMENT_TOKENS:
        return None
    mapped = _EMPLOYMENT_MAP.get(key)
    if mapped is None:
        logger.warning(
            "Unrecognized Zangia employment type {!r} -- employment_type_code "
            "left None; the raw value is preserved in raw_payload.",
            raw,
        )
    return mapped


def _positive(value: int | None) -> int | None:
    """A positive bound passes through; 0/negative means "unstated" -> None."""
    if value is None:
        return None
    return int(value) if int(value) > 0 else None


class ZangiaCleaner:
    """Cleans a batch of validated Zangia records into CleanedJob records."""

    def clean_job(self, raw_job: RawZangiaJob) -> CleanedJob:
        """Clean a single validated Zangia job record."""
        description_parts = [
            clean_html_text(part)
            for part in (
                raw_job.description_html,
                raw_job.requirements_html,
                raw_job.additional_html,
            )
        ]
        description_clean = clean_plain_text(
            "\n\n".join(part for part in description_parts if part)
        )
        location_cleaned = clean_plain_text(raw_job.location_text) or None
        skills = _clean_tags(list(raw_job.skills_raw))
        word_count = len(description_clean.split()) if description_clean else 0

        salary_min = _positive(raw_job.salary_min_raw)
        salary_max = _positive(raw_job.salary_max_raw)
        # Reversed bounds come back occasionally (site data error); swap
        # rather than drop -- the same rule the TimesJobs/Glints cleaners apply.
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            logger.warning(
                "Zangia job {}: reversed salary range (min={}, max={}); "
                "swapping to satisfy ck_job_salaries_range.",
                raw_job.source_job_id,
                salary_min,
                salary_max,
            )
            salary_min, salary_max = salary_max, salary_min
        # A single disclosed bound still counts as disclosed.
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
            # Mongolia board; the board quotes a monthly wage and every
            # sampled row carried a salary object (module docstring).
            currency_iso_code="MNT",
            pay_period="monthly",
            employment_type_code=_map_employment_type(raw_job.employment_type_raw),
        )

    def clean_jobs(self, raw_jobs: list[RawZangiaJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning Zangia job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "Zangia cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
