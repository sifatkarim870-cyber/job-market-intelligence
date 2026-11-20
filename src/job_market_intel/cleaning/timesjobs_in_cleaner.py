"""Cleans validated TimesJobs records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawTimesjobsJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment
calls about meaning.

TimesJobs-specific quirks handled here:

* **Salary is effectively hidden.** Every sampled detail row carried
  ``hideCtcFromCandidate: true`` with ``minCtc``/``maxCtc`` at ``-1``.
  The cleaner drops non-positive bounds (the Glints zero-bound rule),
  honors an explicit ``hideCtcFromCandidate: true`` as a site-side
  withhold, and swaps a reversed pair rather than dropping it.
* **Currency is INR**, evidenced by the board itself: every listing row
  carried ``currency: "INR"`` and TimesJobs is India's board, quoting to
  annual CTC by convention (``pay_period="yearly"``). The detail
  ``ctcCurrency`` is the raw enum ``"r"`` (paise) and is ignored in favor
  of the listing's explicit ISO code.
* **Employment vs. work mode.** ``employmentType`` is usually
  ``"Full-time"`` but occasionally repeats the work mode ``"On-site"``;
  ``jobType`` is always ``"On-site"``. The cleaner maps the recognized
  employment labels onto ``ref.employment_types``, silently ignores the
  work-mode words in that slot, and maps ``jobType`` onto
  ``ref.remote_work_types`` (``on_site``/``hybrid`` observed;
  "Remote" is left unmapped without more detail, the stance the TopJobs
  cleaner documents).
* **Descriptions are HTML** (``description`` plus the optional
  ``desiredCandidate`` and free-text ``perks``); all are folded into one
  cleaned description, since each is job content with no separate
  ``CleanedJob`` slot.
* **Experience is a pair of integers** (``minExperience``/
  ``maxExperience``), with 0 meaning "unstated"; positives flow to
  ``experience_years_min``/``experience_years_max`` after a reversed-pair
  swap.

Tags merge the four labeled arrays the detail offers (``functionNames``,
``aosNames``, ``roleNames``, ``industryNames``) plus the split ``skills``
string -- cleaned, lowercased, de-duplicated. The detail also carries
education course names and a vacancy count; neither has a matching
``CleanedJob`` slot here, so they stay in ``raw_payload`` only.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.timesjobs_in.models import RawTimesjobsJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

#: ``employmentType`` -> ref.employment_types.code. Observed live:
#: "Full-time" (and rare "On-site" rows where the field repeats the work
#: mode). "Internship"/"Contract"/... included defensively.
_EMPLOYMENT_MAP = {
    "full_time": "full_time",
    "part_time": "part_time",
    "internship": "internship",
    "contract": "contract",
    "contractual": "contract",
    "temporary": "temporary",
    "freelance": "freelance",
    "apprenticeship": "apprenticeship",
    "permanent": "full_time",
}

#: The work-mode words that sometimes leak into ``employmentType``;
#: recognized here only so they are ignored without a spurious warning.
_WORK_MODE_WORDS = {"on_site", "onsite", "site", "remote", "hybrid", "work_from_home", "wfh"}

#: ``jobType`` -> ref.remote_work_types.code. "Remote" is deliberately
#: not mapped (no signal here says whether it is city/country/global).
_WORK_MODE_MAP = {
    "on_site": "on_site",
    "onsite": "on_site",
    "hybrid": "hybrid",
}


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
    """Map the detail's ``employmentType`` onto ref.employment_types.code."""
    if not raw:
        return None
    key = _normalize(raw)
    if key in _WORK_MODE_WORDS:
        return None
    mapped = _EMPLOYMENT_MAP.get(key)
    if mapped is None:
        logger.warning(
            "Unrecognized TimesJobs employment type {!r} -- employment_type_code "
            "left None; the raw value is preserved in raw_payload.",
            raw,
        )
    return mapped


def _map_work_mode(raw: str | None) -> str | None:
    """Map the detail's ``jobType`` onto ref.remote_work_types.code.

    "Remote" is deliberately not mapped -- see the module docstring.
    """
    if not raw:
        return None
    return _WORK_MODE_MAP.get(_normalize(raw))


def _positive(value: int | None) -> int | None:
    """A positive bound passes through; 0/negative means "unstated" -> None."""
    if value is None:
        return None
    return int(value) if int(value) > 0 else None


class TimesjobsCleaner:
    """Cleans a batch of validated TimesJobs records into CleanedJob records."""

    def clean_job(self, raw_job: RawTimesjobsJob) -> CleanedJob:
        """Clean a single validated TimesJobs job record."""
        description_parts = [
            clean_html_text(part)
            for part in (
                raw_job.description_html,
                raw_job.desired_candidate_html,
                raw_job.perks_raw,
            )
        ]
        description_clean = clean_plain_text(
            "\n\n".join(part for part in description_parts if part)
        )
        location_cleaned = clean_plain_text(raw_job.location_text) or None
        skills = _clean_tags(list(raw_job.skills_raw) + list(raw_job.function_raws))
        word_count = len(description_clean.split()) if description_clean else 0

        salary_min = _positive(raw_job.salary_min_raw)
        salary_max = _positive(raw_job.salary_max_raw)
        # Explicit site-side withhold: never observed with bounds (flag-True
        # rows carry -1 bounds), so this is defensive, not a sampled rule.
        if raw_job.salary_show_flag is False:
            salary_min = salary_max = None
        # Reversed bounds come back occasionally (site data error); swap
        # rather than drop -- the same rule Glints' cleaner applies.
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            logger.warning(
                "TimesJobs job {}: reversed salary range (min={}, max={}); "
                "swapping to satisfy ck_job_salaries_range.",
                raw_job.source_job_id,
                salary_min,
                salary_max,
            )
            salary_min, salary_max = salary_max, salary_min
        salary_disclosed = salary_min is not None or salary_max is not None

        exp_min = _positive(raw_job.experience_years_min)
        exp_max = _positive(raw_job.experience_years_max)
        if exp_min is not None and exp_max is not None and exp_min > exp_max:
            exp_min, exp_max = exp_max, exp_min

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
            apply_url=raw_job.apply_url or raw_job.original_url,
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
            # India board; every listing row carried currency "INR" and the
            # board quotes annual CTC by convention (module docstring).
            currency_iso_code="INR",
            pay_period="yearly",
            employment_type_code=_map_employment_type(raw_job.employment_type_raw),
            remote_work_type_code=_map_work_mode(raw_job.work_mode_raw),
            experience_years_min=exp_min,
            experience_years_max=exp_max,
        )

    def clean_jobs(self, raw_jobs: list[RawTimesjobsJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning TimesJobs job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "TimesJobs cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
