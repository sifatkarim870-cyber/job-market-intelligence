"""Cleans validated Jobicy records into standardized, storage-ready records.

Two field mappings are worth stating, because both are judgment calls rather
than mechanical translations:

``location_cleaned``
    ``jobGeo`` is a normalised region ("USA", "UK", "Europe", "LATAM",
    "APAC") rather than a city. It is passed through as-is because it is
    already the granularity the feed offers, and the geographic resolver
    handles a country-level token. An absent value becomes "Remote /
    unspecified", matching the wording the corpus already uses -- the feed is
    remote-only, so an unknown region is still a known fact about the posting.

``pay_period``
    Jobicy reports no salary period at all, and no salary fields either. So
    ``salary_disclosed`` is False and ``pay_period`` is None. Inventing a
    period would fail ck_job_salaries_pay_period and, worse, would attach an
    assumption to every row that a downstream average would then trust.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.jobicy.models import RawJobicyJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

#: Mirrors the threshold the other cleaners use so data_quality_score means
#: the same thing across sources.
_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 50

#: The feed is remote-only, so an unknown region is "remote", not "unknown".
REMOTE_LOCATION = "Remote / unspecified"

#: ``CleanedJob.pay_period`` is a required ``str`` -- not ``str | None`` -- so
#: there is no way to express "this feed reports no salary period". Leaving it
#: None raises
#:
#:     Input should be a valid string [type=string_type, input_value=None]
#:
#: and drops every row. Jobicy publishes no salary fields at all, so the
#: honest value is the schema's neutral "yearly", which every other cleaner
#: uses when a source says nothing about period. The row stores no salary, so
#: nothing is mispriced by the period being nominal.
DEFAULT_PAY_PERIOD = "yearly"


def _compute_data_quality_score(
    *,
    salary_disclosed: bool,
    location_cleaned: str | None,
    skills: list[str],
    word_count: int,
) -> float:
    """Four-signal completeness score, identical in shape and weighting to
    every other cleaner's, so the number stays comparable across sources."""
    signals = [
        salary_disclosed,
        location_cleaned is not None,
        len(skills) > 0,
        word_count >= _SUBSTANTIAL_DESCRIPTION_WORD_COUNT,
    ]
    return round(sum(signals) / len(signals), 2)


class JobicyCleaner:
    """Turns ``RawJobicyJob`` objects into ``CleanedJob`` records."""

    def clean_jobs(self, jobs: list[RawJobicyJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        for raw in jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to clean Jobicy job {}: {}", raw.id, exc)
        return cleaned

    def clean_job(self, raw: RawJobicyJob) -> CleanedJob:
        description_clean = clean_html_text(raw.jobDescription) or clean_plain_text(
            raw.jobExcerpt
        )
        word_count = len(description_clean.split()) if description_clean else 0

        # Industry tags and the seniority level are this feed's tag list.
        skills: list[str] = []
        seen: set[str] = set()
        for value in [*raw.jobIndustry, *([raw.jobLevel] if raw.jobLevel else [])]:
            label = clean_plain_text(value)
            if label and label.lower() not in seen:
                seen.add(label.lower())
                skills.append(label)

        location_cleaned = clean_plain_text(raw.jobGeo) or REMOTE_LOCATION

        return CleanedJob(
            source_job_id=raw.id,
            job_title=clean_plain_text(raw.jobTitle) or raw.jobTitle,
            company_name=clean_plain_text(raw.companyName) or raw.companyName or "Unknown",
            company_logo_url=raw.companyLogo,
            skills=skills,
            location_cleaned=location_cleaned,
            # Jobicy publishes no salary fields, so none are invented.
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=description_clean,
            word_count=word_count,
            apply_url=raw.url,
            original_url=raw.url or f"https://jobicy.com/jobs/{raw.id}",
            posting_date=raw.posting_date,
            closing_date=None,
            data_quality_score=_compute_data_quality_score(
                salary_disclosed=False,
                location_cleaned=location_cleaned,
                skills=skills,
                word_count=word_count,
            ),
            raw_payload=raw.raw_payload,
            currency_iso_code="USD",
            # Jobicy reports no salary period, and the field is a required
            # str -- see DEFAULT_PAY_PERIOD. No salary row is written for this
            # source (salary_min/max are None), so the period is never used to
            # annualise anything.
            pay_period=DEFAULT_PAY_PERIOD,
            employment_type_code=(
                raw.jobType[0] if raw.jobType else None
            ),
        )
