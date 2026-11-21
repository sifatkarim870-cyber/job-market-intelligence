"""Cleans validated ANPE Mali records into storage-ready records.

Same boundary as the other cleaners: ``RawAnpeMaliJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment calls
about meaning.

ANPE-Mali-specific quirks handled here (measured on all 15 listings,
2026-11-21):

* **No salary is ever stated.** ``meta._job_salary`` (and its
  ``_job_salary_currency`` / ``_job_salary_unit`` companions) is the empty
  string on every listing, so ``salary_disclosed`` is always False and no
  bounds are invented. Currency is XOF (Mali's CFA franc). ``pay_period``
  is a required str on ``CleanedJob`` with no "unknown" member, so it
  takes ``DEFAULT_PAY_PERIOD`` -- the same inert placeholder Jobicy, Reed,
  TheMuse and ANPE-BF use -- and is never used to annualise anything.
* **Location is a free-text field.** ``meta._job_location`` holds
  "Bamako" (8), "Mali"/"MALI" (3), "Sur site" (4) and "" (1). "Sur site"
  is a work arrangement ("on-site"), not a place, so it is dropped from
  ``location_cleaned`` and recorded as ``on_site`` instead; the row then
  still resolves to Mali through ``SOURCE_HOME_COUNTRY``.
* **Contract type is a taxonomy.** ``class_list`` carries
  ``job-type-<slug>``: cdi -> ``full_time``, cdd -> ``contract``,
  interim -> ``temporary``, independant -> ``freelance``, stage ->
  ``internship``. A ``job-types`` id is used only when ``class_list`` is
  absent. When a listing carries more than one distinct type the mapping
  is left unset rather than guessed (the same multi-value -> NULL rule the
  AfricaWork boards use).
* **Employer IS present** (unlike ANPE BF): ``meta._company_name`` is the
  hiring organisation, and the logo comes from the embedded
  ``wp:featuredmedia`` object. When no employer is named the agency itself
  is used and no client is guessed from the title.
* **No skills are published**; ``skills`` stays empty. The shared
  skill-extraction step can mine the description later.
"""

from __future__ import annotations

import re

from loguru import logger

from job_market_intel.scrapers.anpe_mali.models import JOB_TYPE_ID_TO_SLUG, RawAnpeMaliJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

#: ``CleanedJob.pay_period`` is a required ``str`` with no "unknown" member.
#: No ANPE Mali listing states a salary, let alone a period, so this
#: documented placeholder is carried only to satisfy the model -- with
#: ``salary_min``/``salary_max`` both None, nothing is ever annualised from
#: it. Matches the Jobicy/Reed/TheMuse/ANPE-BF convention.
DEFAULT_PAY_PERIOD = "yearly"

#: ``job-type-<slug>`` -> ref.employment_types.code.
_SLUG_TO_CODE: dict[str, str] = {
    "cdi": "full_time",
    "cdd": "contract",
    "interim": "temporary",
    "independant": "freelance",
    "stage": "internship",
}

#: ``job-types`` term id -> ref.employment_types.code (class_list fallback).
_ID_TO_CODE: dict[int, str] = {
    term_id: _SLUG_TO_CODE[slug] for term_id, slug in JOB_TYPE_ID_TO_SLUG.items()
}

#: "Sur site" (and English on-site variants) name a work arrangement, not a
#: place, so they become ``on_site`` instead of a location.
_ON_SITE = re.compile(
    r"^\s*(?:sur[\s\-]?site|on[\s\-]?site|onsite|pr[ée]sentiel)\s*$",
    re.IGNORECASE,
)


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


def extract_location(location_raw: str | None) -> tuple[str | None, str | None]:
    """Split a free-text location into ``(location, remote_work_type_code)``.

    Returns:
        ``(None, "on_site")`` for an on-site phrase, ``(place, None)`` for a
        real place, and ``(None, None)`` when nothing usable is present.
    """
    if not location_raw:
        return None, None
    text = (clean_plain_text(location_raw) or location_raw).strip()
    if not text:
        return None, None
    if _ON_SITE.match(text):
        return None, "on_site"
    return text, None


def map_employment_type(slugs: list[str], ids: list[int]) -> str | None:
    """Map the listing's contract taxonomy onto ref.employment_types.code.

    ``class_list`` slugs win; the ``job-types`` ids are a fallback. More
    than one distinct code means the row is ambiguous and stays unset.
    """
    codes = {_SLUG_TO_CODE[slug] for slug in slugs if slug in _SLUG_TO_CODE}
    if not codes:
        codes = {_ID_TO_CODE[term_id] for term_id in ids if term_id in _ID_TO_CODE}
    if len(codes) == 1:
        return next(iter(codes))
    return None


class AnpeMaliCleaner:
    """Cleans a batch of validated ANPE Mali records into CleanedJob."""

    def clean_job(self, raw_job: RawAnpeMaliJob) -> CleanedJob:
        """Clean a single validated ANPE Mali record."""
        description_clean = clean_html_text(raw_job.description_html) or ""
        title = clean_plain_text(raw_job.job_title) or raw_job.job_title
        location_cleaned, remote_code = extract_location(raw_job.location_raw)
        word_count = len(description_clean.split()) if description_clean else 0
        skills: list[str] = []

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=title,
            company_name=clean_plain_text(raw_job.company_name) or raw_job.company_name,
            company_logo_url=raw_job.company_logo_url,
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
            closing_date=None,
            data_quality_score=_compute_data_quality_score(
                salary_disclosed=False,
                location_cleaned=location_cleaned,
                skills=skills,
                word_count=word_count,
            ),
            raw_payload=raw_job.raw_payload,
            # Mali's CFA franc; the listings never quote pay, so
            # salary_disclosed is False and no bounds are invented. The
            # required pay_period str takes the documented inert default.
            currency_iso_code="XOF",
            pay_period=DEFAULT_PAY_PERIOD,
            employment_type_code=map_employment_type(
                raw_job.employment_type_slugs, raw_job.job_type_ids
            ),
            remote_work_type_code=remote_code,
        )

    def clean_jobs(self, raw_jobs: list[RawAnpeMaliJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning ANPE Mali record {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "ANPE Mali cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
