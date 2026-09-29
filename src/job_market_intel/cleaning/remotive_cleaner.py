"""Cleans validated Remotive records into standardized, storage-ready records.

See ``cleaning/remoteok_cleaner.py``'s module docstring for the overall
boundary this module keeps: it takes a validated-but-still-messy
``RawRemotiveJob`` and produces a ``CleanedJob`` (``cleaning/common.py``),
same "only remove noise with no analytical value, never make judgment
calls about meaning" principle, and the same explicit list of things this
deliberately does NOT do (company resolution, geographic resolution,
skill extraction, currency conversion, content-hash computation — all
later, separate steps).

Genuine differences from ``RemoteOKCleaner``/``WWRCleaner``, each
following directly from structural facts about Remotive's API confirmed
while building ``scrapers/remotive/models.py`` (see that module's
docstring):

    - No salary repair to do here, unlike RemoteOK. RemoteOK's structured
      salary fields can arrive with min/max reversed (a source-side data-
      entry mistake); Remotive has no structured salary fields at all —
      only free text, already conservatively parsed (or left as ``None``)
      by ``RawRemotiveJob``'s own model-level parsing. There is nothing
      left to swap by the time a ``RawRemotiveJob`` reaches this cleaner.
    - ``closing_date`` is never populated, same honest gap as RemoteOK —
      Remotive's API has no posting-expiration field (unlike WWR's
      ``expires_at``).
    - Location is a single raw string (``location_raw``), same shape as
      RemoteOK's ``location_raw``, not WWR's three-way region/country/state
      split.
    - ``tags`` -> ``CleanedJob.skills`` mapping reuses the exact same
      clean/lowercase/dedupe logic as RemoteOK's ``_clean_tags`` — see
      that function's docstring for the rationale, which applies
      identically here. Kept as its own copy rather than imported from
      ``remoteok_cleaner.py`` to preserve each source cleaner's
      established independence (see ``cleaning/__init__.py``'s note on
      waiting for genuine, repeated duplication before extracting further).
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.remotive.models import RawRemotiveJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text


def _clean_tags(raw_tags: list[str]) -> list[str]:
    """Clean, lowercase, and de-duplicate Remotive's raw tags, preserving first-seen order.

    Identical logic to ``remoteok_cleaner._clean_tags`` — see that
    function's docstring for why lowercasing happens here. The result of
    this function becomes ``CleanedJob.skills``.
    """
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


#: Minimum word count for a description to count as "substantial" in the
#: completeness score below. Reused unchanged from
#: ``remoteok_cleaner._SUBSTANTIAL_DESCRIPTION_WORD_COUNT`` — see that
#: constant's docstring for the rationale, which applies identically here.
_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20


def _compute_data_quality_score(
    *,
    salary_disclosed: bool,
    location_cleaned: str | None,
    skills: list[str],
    word_count: int,
) -> float:
    """Compute a 0.0-1.0 completeness score from already-cleaned fields.

    The exact same four-signal, equally-weighted formula
    ``remoteok_cleaner._compute_data_quality_score``/
    ``weworkremotely_cleaner._compute_data_quality_score`` use — see
    ``weworkremotely_cleaner``'s copy of this docstring for why reusing
    the identical weighting (rather than reweighting per source) keeps the
    score comparable across sources. One honest consequence worth
    knowing, specific to Remotive: because ``salary_disclosed`` is only
    ``True`` for the subset of postings whose free-text ``salary`` field
    happened to match the conservative "$X - $Y" pattern
    ``RawRemotiveJob`` parses (see that module's docstring), a Remotive
    job that genuinely has salary information Remotive just phrased
    differently (a single figure, "+"-suffixed, non-USD) will still show
    ``salary_disclosed=False`` here. That's not a defect in the score —
    it's an accurate reflection of what this pipeline stage can safely
    extract, not what the source technically provides.

    Returns:
        The fraction of the four signals present, rounded to 2 decimal
        places to match the schema's ``NUMERIC(3,2)`` column type.
    """
    signals = [
        salary_disclosed,
        location_cleaned is not None,
        len(skills) > 0,
        word_count >= _SUBSTANTIAL_DESCRIPTION_WORD_COUNT,
    ]
    return round(sum(signals) / len(signals), 2)


class RemotiveCleaner:
    """Cleans a batch of validated Remotive records into CleanedJob records."""

    def clean_job(self, raw_job: RawRemotiveJob) -> CleanedJob:
        """Clean a single validated Remotive job record.

        Args:
            raw_job: A ``RawRemotiveJob`` produced by ``RemotiveParser``.

        Returns:
            The corresponding ``CleanedJob``.
        """
        description_clean = clean_html_text(raw_job.description_raw)
        location_cleaned = clean_plain_text(raw_job.location_raw)
        skills = _clean_tags(raw_job.tags)
        salary_disclosed = raw_job.salary_min is not None or raw_job.salary_max is not None
        word_count = len(description_clean.split()) if description_clean else 0

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=clean_plain_text(raw_job.job_title) or raw_job.job_title,
            company_name=clean_plain_text(raw_job.company_name) or raw_job.company_name,
            company_logo_url=raw_job.company_logo_url,
            skills=skills,
            location_cleaned=location_cleaned,
            salary_min=raw_job.salary_min,
            salary_max=raw_job.salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=description_clean,
            word_count=word_count,
            # Remotive's API offers no distinct "apply URL" separate from
            # the job's own page (unlike RemoteOK, which sometimes
            # provides one) — same fallback behavior WWR's cleaner
            # already documents for a source with only one URL.
            apply_url=raw_job.original_url,
            original_url=raw_job.original_url,
            posting_date=raw_job.posting_date,
            # closing_date intentionally omitted (stays None): Remotive's
            # API has no posting-expiration field, same honest gap as
            # RemoteOK — see the module docstring.
            data_quality_score=_compute_data_quality_score(
                salary_disclosed=salary_disclosed,
                location_cleaned=location_cleaned,
                skills=skills,
                word_count=word_count,
            ),
            raw_payload=raw_job.raw_payload,
            # Remotive's free-text salary parser only matches whole-dollar
            # range strings typical of annual tech-salary postings --
            # stated explicitly here now that db.job_repository no longer
            # assumes this on every source's behalf (see that module's
            # "Reed scraper note"). Preserves this source's exact previous
            # stored behavior.
            currency_iso_code="USD",
            pay_period="yearly",
        )

    def clean_jobs(self, raw_jobs: list[RawRemotiveJob]) -> list[CleanedJob]:
        """Clean a batch of validated Remotive job records.

        Mirrors ``RemoteOKCleaner.clean_jobs``'s/``WWRCleaner.clean_jobs``'s
        skip-don't-crash philosophy exactly — every input record already
        passed schema validation, so a cleaning failure here is
        unexpected, but one unexpected error should still not take down
        the rest of an otherwise-healthy batch.

        Args:
            raw_jobs: Validated records from ``RemotiveParser.parse_jobs()``.

        Returns:
            Cleaned records. May be shorter than ``raw_jobs`` if any
            individual record failed to clean (logged when this happens).
        """
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
                logger.error(
                    "Unexpected error cleaning Remotive job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "Remotive cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
