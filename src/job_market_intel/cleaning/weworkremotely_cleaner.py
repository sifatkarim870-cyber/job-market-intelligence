"""Cleans validated We Work Remotely records into standardized, storage-ready records.

See ``cleaning/remoteok_cleaner.py``'s module docstring for the overall
boundary this module keeps: it takes a validated-but-still-messy
``RawWWRJob`` and produces a ``CleanedJob`` (``cleaning/common.py``),
same "only remove noise with no analytical value, never make judgment
calls about meaning" principle, and the same explicit list of things
this deliberately does NOT do (company resolution, geographic
resolution, skill extraction, currency conversion, content-hash
computation — all later, separate steps).

Genuine differences from ``RemoteOKCleaner``, each following directly
from structural facts about We Work Remotely's feed confirmed while
building ``scrapers/weworkremotely/models.py`` (see that module's
docstring):

    - No salary repair to do. There is nothing to swap — WWR's feed has
      no structured salary fields at all, so every ``CleanedJob`` built
      here has ``salary_min``/``salary_max`` = ``None`` and
      ``salary_disclosed`` = ``False``, unconditionally. This is an
      honest reflection of what this source can provide at this stage,
      not a bug — extracting a figure from free text belongs to a later
      NLP-driven step.
    - Location is joined from three raw signals (``region_raw``,
      ``country_raw``, ``state_raw``), not resolved from one. Simple,
      naive concatenation of whichever parts are present — no attempt is
      made to judge which of the three is most trustworthy (see
      ``models.py``'s note on ``state_raw``'s uncertain reliability); an
      editorial "drop the field that looks unreliable" call is exactly
      the kind of judgment call this layer is not supposed to make.
    - A description-trailer strip specific to WWR: every posting's raw
      HTML ends with a mechanically-appended "To apply: <url>" paragraph
      that duplicates ``CleanedJob.original_url`` outright. Removed here
      as pure duplication, same principle as RemoteOK's stray-trailing-
      comma location cleanup — content-neutral noise removal, not
      interpretation.
    - ``closing_date`` is passed through from ``RawWWRJob.closing_date``
      — a field RemoteOK's cleaner never populated because RemoteOK's
      feed never provided one.
"""

from __future__ import annotations

import re

from loguru import logger

from job_market_intel.scrapers.weworkremotely.models import RawWWRJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

#: Matches We Work Remotely's mechanically-appended "To apply: <url>"
#: trailer at the very end of a cleaned description. Matched by pattern
#: (not by comparing against the job's own known URL) so it degrades
#: gracefully if WWR ever changes the exact wording slightly, and works
#: regardless of which URL happens to be present.
_TO_APPLY_TRAILER_PATTERN = re.compile(r"\s*To apply:\s*\S+\s*$", re.IGNORECASE)


def _strip_apply_trailer(description_clean: str | None) -> str | None:
    """Remove WWR's mechanically-appended "To apply: <url>" trailer.

    Every We Work Remotely posting's raw HTML ends with a paragraph
    reading "To apply: <job URL>" — pure duplication of information
    already captured structurally in ``CleanedJob.original_url``,
    appended by WWR itself to every description regardless of content.
    Removing it here is content-neutral: it never removes anything with
    analytical value, only a mechanical, source-injected trailer.
    """
    if description_clean is None:
        return None
    stripped = _TO_APPLY_TRAILER_PATTERN.sub("", description_clean).strip()
    return stripped or None


def _clean_skills(raw_skills: list[str]) -> list[str]:
    """Clean, lowercase, and de-duplicate WWR's skills, preserving first-seen order.

    Mirrors ``remoteok_cleaner._clean_tags`` exactly — see that
    function's docstring for why lowercasing happens here. WWR's
    ``RawWWRJob.skills`` has already been split from the feed's single
    comma-separated string into a list by this point (see
    ``models.py``); this function only cleans individual entries, same
    as RemoteOK's tags.
    """
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw_skill in raw_skills:
        cleaned_skill = clean_plain_text(raw_skill)
        if not cleaned_skill:
            continue
        normalized = cleaned_skill.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return cleaned


def _clean_location(
    region_raw: str | None, country_raw: str | None, state_raw: str | None
) -> str | None:
    """Join We Work Remotely's three raw location signals into one cleaned string.

    Naive concatenation of whichever of ``region_raw``/``country_raw``/
    ``state_raw`` are present after individual cleaning — no field is
    dropped or preferred over another. This is intentionally still just
    string cleanup, not geographic resolution or a judgment call about
    which signal is most trustworthy; see the module docstring for why
    ``state_raw`` in particular is kept rather than special-cased out.
    """
    parts: list[str] = []
    for raw_value in (region_raw, country_raw, state_raw):
        cleaned = clean_plain_text(raw_value)
        if cleaned:
            parts.append(cleaned)
    return "; ".join(parts) if parts else None


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

    Deliberately the exact same four-signal, equally-weighted formula
    ``remoteok_cleaner._compute_data_quality_score`` uses — reusing the
    identical weighting (rather than reweighting for a source that
    structurally lacks one signal) keeps the score comparable across
    sources, which is the entire point of a shared completeness metric.
    One honest consequence worth knowing: since ``salary_disclosed`` is
    always ``False`` for We Work Remotely (see the module docstring),
    every WWR job's score is capped at 0.75 even when the other three
    signals are all present. That's not a defect in the score — it's an
    accurate reflection of what this source structurally provides at
    this pipeline stage.

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


class WWRCleaner:
    """Cleans a batch of validated We Work Remotely records into CleanedJob records."""

    def clean_job(self, raw_job: RawWWRJob) -> CleanedJob:
        """Clean a single validated We Work Remotely job record.

        Args:
            raw_job: A ``RawWWRJob`` produced by ``WWRParser``.

        Returns:
            The corresponding ``CleanedJob``.
        """
        description_clean = clean_html_text(raw_job.description_raw)
        description_clean = _strip_apply_trailer(description_clean)
        location_cleaned = _clean_location(
            raw_job.region_raw, raw_job.country_raw, raw_job.state_raw
        )
        skills = _clean_skills(raw_job.skills)
        word_count = len(description_clean.split()) if description_clean else 0

        # We Work Remotely's RSS feed has no structured salary field at
        # all (unlike RemoteOK, which always sends salary_min/salary_max
        # fields, sometimes as a literal 0 meaning "undisclosed"). Any
        # salary mentioned on a WWR posting lives only in free text
        # inside the description; extracting it from there is an NLP
        # task belonging to a later phase, not text cleaning. So every
        # WWR CleanedJob has salary_disclosed=False here, honestly
        # reflecting what this source structurally provides at this
        # stage of the pipeline.
        salary_min: int | None = None
        salary_max: int | None = None
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
            # WWR's feed offers no distinct "apply URL" separate from the
            # job's own page (unlike RemoteOK, which sometimes provides
            # one) -- the job page URL is the only URL WWR gives us, so
            # it serves double duty here, same fallback behavior
            # RemoteOKCleaner already documents for when RemoteOK itself
            # doesn't provide a distinct apply link.
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
            # WWR has no salary field at all -- salary_min/salary_max are
            # always None above, so these two values are never actually
            # used for normalization, but CleanedJob requires them stated
            # regardless (see db.job_repository's "Reed scraper note").
            # Kept as the same USD/yearly convention the other two live
            # sources use, purely for consistency; harmless either way
            # since there's never a real figure to normalize.
            currency_iso_code="USD",
            pay_period="yearly",
        )

    def clean_jobs(self, raw_jobs: list[RawWWRJob]) -> list[CleanedJob]:
        """Clean a batch of validated We Work Remotely job records.

        Mirrors ``RemoteOKCleaner.clean_jobs``'s skip-don't-crash
        philosophy exactly — every input record already passed schema
        validation, so a cleaning failure here is unexpected, but one
        unexpected error should still not take down the rest of an
        otherwise-healthy batch.

        Args:
            raw_jobs: Validated records from ``WWRParser.parse_jobs()``.

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
                    "Unexpected error cleaning We Work Remotely job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "We Work Remotely cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
