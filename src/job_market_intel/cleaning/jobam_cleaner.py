"""Cleans validated Job.am records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawJobAmJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment calls
about meaning.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.jobam.models import RawJobAmJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

# job.am's JSON-LD employmentType, observed over the first 100 listings
# (2026-10-05): "Full Time" (81), "Flexible" (5), "Part Time" (3),
# "Full Time, Part Time" (2), "Part Time, Flexible" (1),
# "Full Time, Flexible" (1), "Contract" (1). Segments are matched
# against ref.employment_types.code; "Flexible" deliberately has no
# target — Armenia's flexible-hours contract form is not any of the
# seven reference codes, so it stays None (honest absence) rather than
# being shoehorned into part_time.
_EMPLOYMENT_SEGMENT_MAP = {
    "full time": "full_time",
    "part time": "part_time",
    "contract": "contract",
    "temporary": "temporary",
    "internship": "internship",
    "freelance": "freelance",
    "apprenticeship": "apprenticeship",
}


def _map_employment_type(employment_type_raw: str | None) -> str | None:
    """Map job.am's multi-valued ``employmentType`` to one reference code.

    Multi-valued strings are read left to right ("Full Time, Part Time"
    -> ``full_time``: the first listed contract form wins), and unknown
    solo values ("Flexible") fall through to ``None`` with a warning —
    the real string stays in ``raw_payload`` either way.
    """
    if not employment_type_raw:
        return None
    segments = [segment.strip().lower().replace("-", " ") for segment in employment_type_raw.split(",")]
    for segment in segments:
        mapped = _EMPLOYMENT_SEGMENT_MAP.get(segment)
        if mapped:
            return mapped
    normalized = employment_type_raw.lower()
    for key, value in _EMPLOYMENT_SEGMENT_MAP.items():
        if key in normalized:
            return value
    logger.warning(
        "Unrecognized Job.am employmentType {!r} -- employment_type_code "
        "left None; the real value is still preserved in raw_payload.",
        employment_type_raw,
    )
    return None


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


class JobAmCleaner:
    """Cleans a batch of validated Job.am records into CleanedJob records."""

    def clean_job(self, raw_job: RawJobAmJob) -> CleanedJob:
        """Clean a single validated Job.am job record."""
        description_clean = clean_html_text(raw_job.description_raw)
        location_cleaned = clean_plain_text(raw_job.location_raw)
        # job.am's list payload carries no tags/keywords at all (the
        # nine keys are Id/Title/Company/Url/Logo/DeadLine/Location/
        # IndustryId/IndustryIds), so skills start empty here and the
        # separate skill-extraction batch fills bridge.job_skills from
        # the description — same path Indeed's jobs take.
        skills: list[str] = []
        word_count = len(description_clean.split()) if description_clean else 0

        # No salary field exists anywhere in job.am's payloads (list,
        # JSON-LD, or page), so this is honest absence. AMD/yearly is
        # recorded as the source's currency context, mirroring how
        # Emploitic records DZD/yearly with no salary data either —
        # it stays inert (no salary rows, no FX conversion) unless a
        # future payload actually carries pay.
        salary_min, salary_max = None, None
        salary_disclosed = False

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
            currency_iso_code="AMD",
            pay_period="yearly",
            employment_type_code=_map_employment_type(raw_job.employment_type_raw),
        )

    def clean_jobs(self, raw_jobs: list[RawJobAmJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning Job.am job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "Job.am cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
