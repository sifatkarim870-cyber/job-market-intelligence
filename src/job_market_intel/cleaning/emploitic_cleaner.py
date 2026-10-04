"""Cleans validated Emploitic records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawEmploiticJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment calls
about meaning.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.emploitic.models import RawEmploiticJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20


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


_CONTRACT_TYPE_MAP = {
    "cdi": "full_time",
    "cdd": "contract",
    "cdd ou mission": "contract",
    "mission": "contract",
    "interim": "temporary",
    "freelance": "contract",
    "stage": "temporary",
    "intérim": "temporary",
}


def _map_employment_type(contract_type_raw: str | None) -> str | None:
    """Map Emploitic's French contractType onto ref.employment_types.code.

    Unknown/absent values yield ``None`` (honest absence) and are logged,
    same philosophy as the other cleaners. The mapping is intentionally
    conservative: anything not recognized falls through to ``None``
    rather than being guessed at.
    """
    if not contract_type_raw:
        return None
    normalized = contract_type_raw.strip().lower()
    mapped = _CONTRACT_TYPE_MAP.get(normalized)
    if mapped is None:
        # Substring check catches compound labels like "CDD Ou Mission".
        for key, value in _CONTRACT_TYPE_MAP.items():
            if key in normalized:
                return value
        logger.warning(
            "Unrecognized Emploitic contractType {!r} -- employment_type_code "
            "left None; the real value is still preserved in raw_payload.",
            contract_type_raw,
        )
        return None
    return mapped


class EmploiticCleaner:
    """Cleans a batch of validated Emploitic records into CleanedJob records."""

    def clean_job(self, raw_job: RawEmploiticJob) -> CleanedJob:
        """Clean a single validated Emploitic job record."""
        description_clean = clean_html_text(raw_job.description_raw)
        location_cleaned = clean_plain_text(raw_job.location_raw)
        skills = _clean_tags(raw_job.tags)
        word_count = len(description_clean.split()) if description_clean else 0

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=clean_plain_text(raw_job.job_title) or raw_job.job_title,
            company_name=clean_plain_text(raw_job.company_name) or raw_job.company_name,
            company_logo_url=None,
            skills=skills,
            location_cleaned=location_cleaned,
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=description_clean,
            word_count=word_count,
            apply_url=raw_job.original_url,
            original_url=raw_job.original_url,
            posting_date=raw_job.posting_date,
            data_quality_score=_compute_data_quality_score(
                salary_disclosed=False,
                location_cleaned=location_cleaned,
                skills=skills,
                word_count=word_count,
            ),
            raw_payload=raw_job.raw_payload,
            # Emploitic's listing payload carries no salary information at
            # all (confirmed live) — same treatment as choosing honest
            # defaults elsewhere: no currency is asserted.
            currency_iso_code="DZD",
            pay_period="yearly",
            employment_type_code=_map_employment_type(raw_job.contract_type_raw),
        )

    def clean_jobs(self, raw_jobs: list[RawEmploiticJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning Emploitic job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "Emploitic cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
