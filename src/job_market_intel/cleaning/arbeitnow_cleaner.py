"""Cleans validated Arbeitnow records into standardized, storage-ready records.

Follows the boundary every other cleaner in this project keeps: take a
validated-but-messy ``RawArbeitnowJob`` and produce a ``CleanedJob``, only
removing noise, never making judgment calls about meaning. Company resolution,
geographic resolution, skill extraction, currency conversion and content-hash
computation are all later, separate steps.

Genuine differences from the existing cleaners, each following from a
structural fact about Arbeitnow's API:

    - ``description`` is HTML, so ``clean_html_text`` does real work -- these
      are complete descriptions, not teasers.
    - ``created_at`` is a unix timestamp, already converted to a datetime by
      the model, so it maps straight onto ``posting_date``.
    - ``job_types`` and ``tags`` are both lists of free-text labels and both
      arrive populated on most postings, so both feed ``CleanedJob.skills``.
      They are concatenated rather than one being preferred, because Arbeitnow
      uses them for different things (employment type vs. topic tags) and
      dropping either would lose signal.
    - No salary, no closing date, no logo. ``currency_iso_code`` and
      ``pay_period`` are still set because ``CleanedJob`` requires them
      explicitly; that is a schema requirement, not a claim that Arbeitnow
      publishes compensation.
"""

from __future__ import annotations

import html

from loguru import logger

from job_market_intel.scrapers.arbeitnow.models import RawArbeitnowJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

#: A description must reach this many words to count as "substantial", for the
#: same reason and with the same value the other cleaners use -- so scores stay
#: comparable across sources.
_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 50


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


def _strip_arbeitnow_html(content: str) -> str:
    """Turn Arbeitnow's ``description`` field into plain text.

    Arbeitnow DOUBLE-ENCODES, exactly as Greenhouse does: the JSON carries HTML
    that has itself been entity-escaped, so the value arrives as
    ``&lt;h2&gt;&lt;strong&gt;...&lt;/strong&gt;&lt;/h2&gt;``. Fed straight to
    ``clean_html_text``, BeautifulSoup parses it as TEXT rather than markup, so
    it decodes the entities and hands back literal ``<h2>`` tags -- which then
    land in ``description_clean`` and in the translation prompt. 19 of 325 live
    postings were affected.

    Fixed by unescaping once here, then running the shared cleaner. Kept local
    to this cleaner rather than changing ``clean_html_text``, because no other
    source double-encodes and a second unescape pass would corrupt theirs.
    """
    if not content:
        return ""
    return clean_html_text(html.unescape(content)) or ""


class ArbeitnowCleaner:
    """Cleans a batch of validated Arbeitnow records into CleanedJob records."""

    def clean_job(self, raw_job: RawArbeitnowJob) -> CleanedJob:
        """Clean one validated Arbeitnow posting."""
        description_clean = _strip_arbeitnow_html(raw_job.description)
        location_cleaned = clean_plain_text(raw_job.location) or None
        # Arbeitnow's own remote flag beats parsing the location string for the
        # word "remote", which appears in ordinary city names too.
        if raw_job.is_remote and not location_cleaned:
            location_cleaned = "Remote"
        skills = [clean_plain_text(s) for s in [*raw_job.job_types, *raw_job.tags]]
        skills = [s for s in skills if s]
        salary_disclosed = False
        word_count = len(description_clean.split()) if description_clean else 0

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=clean_plain_text(raw_job.title) or raw_job.title,
            company_name=clean_plain_text(raw_job.company_name) or raw_job.company_name,
            company_logo_url=None,
            skills=skills,
            location_cleaned=location_cleaned,
            salary_min=None,
            salary_max=None,
            salary_disclosed=salary_disclosed,
            description_clean=description_clean,
            word_count=word_count,
            # Arbeitnow exposes exactly one URL, the public posting page, which
            # is both the canonical reference and where a human applies.
            apply_url=raw_job.url,
            original_url=raw_job.url,
            posting_date=raw_job.created_at,
            # closing_date intentionally omitted: Arbeitnow exposes no
            # posting-expiration field.
            data_quality_score=_compute_data_quality_score(
                salary_disclosed=salary_disclosed,
                location_cleaned=location_cleaned,
                skills=skills,
                word_count=word_count,
            ),
            raw_payload=raw_job.model_dump(mode="json"),
            currency_iso_code="USD",
            pay_period="yearly",
        )

    def clean_jobs(self, raw_jobs: list[RawArbeitnowJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) individual bad records."""
        cleaned: list[CleanedJob] = []
        skipped = 0
        for raw_job in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - one bad row is not the batch
                skipped += 1
                logger.warning("skipping Arbeitnow posting slug={}: {}", raw_job.source_job_id, exc)
        if skipped:
            logger.warning(
                "skipped {} of {} Arbeitnow records while cleaning", skipped, len(raw_jobs)
            )
        return cleaned
