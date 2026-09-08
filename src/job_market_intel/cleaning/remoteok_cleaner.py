"""Cleans validated RemoteOK records into standardized, storage-ready records.

Where this fits: ``scrapers/remoteok/parser.py`` (Step 6) validates that a
record has the right *shape* (required fields present, right types). This
module takes that validated-but-still-messy ``RawRemoteOKJob`` and produces
a ``CleanedJob`` (``cleaning/common.py``) — text fixed (encoding, HTML
entities, HTML tags, whitespace), obvious data-entry mistakes repaired
(swapped salary bounds), and a couple of fields pre-derived that the
database schema itself expects (``salary_disclosed``, ``word_count``).

``CleanedJob`` is the source-agnostic output contract every scraper's
cleaner is expected to produce (see ``cleaning/common.py`` for why); this
module is the RemoteOK-specific logic that gets a ``RawRemoteOKJob`` there.
RemoteOK calls its skill/tag list ``tags`` — this module is the boundary
where that gets mapped onto ``CleanedJob.skills``, matching the schema's
own vocabulary (``ref.skills``).

What this module deliberately does NOT do — these are later, separate
steps, and mixing them in here would blur boundaries the rest of this
codebase has been careful to keep sharp:
    - Resolve ``company_name`` to a canonical ``core.companies`` row
      (Step 25 — company resolution needs fuzzy matching across MULTIPLE
      sources, which doesn't exist yet with only RemoteOK live).
    - Resolve ``location_cleaned`` to a ``ref.locations`` row (Step 28 —
      geographic normalization).
    - Extract structured skills from ``tags``/``description_clean``
      (Step 26 — skill extraction).
    - Convert/normalize currency (Step 27 — RemoteOK salaries are already
      USD, but the general currency-conversion machinery is a separate
      step for when non-USD sources are added).
    - Compute ``content_hash`` for change detection (Step 9/10a — that's
      tied to database insert/update logic, not cleaning).

This module only removes noise that has no analytical value in any form
(garbled characters, markup, stray whitespace) and fixes clear mechanical
errors (min/max salary swapped). It does not make judgment calls about
what the data *means*.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.remoteok.models import RawRemoteOKJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text


def _clean_tags(raw_tags: list[str]) -> list[str]:
    """Clean, lowercase, and de-duplicate RemoteOK's raw tags, preserving first-seen order.

    Lowercasing is applied because skill/tag matching downstream (Step 26)
    is expected to be case-insensitive, matching ``ref.skills.normalized_skill_name``'s
    own lowercased convention in the schema. The original casing is not
    lost — it still lives in ``raw_payload``. The result of this function
    becomes ``CleanedJob.skills``.
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


def _clean_location(raw_location: str | None) -> str | None:
    """Clean a raw location string and strip RemoteOK's stray-trailing-comma quirk.

    Observed live on RemoteOK: some postings return a location like
    ``"Success,"`` or ``"Mangalagiri,"`` — a trailing comma with nothing
    after it, presumably where a country name is normally appended. This
    is cosmetic noise, not meaningful data, so it's removed here. This is
    intentionally still just string cleanup, not geographic resolution.
    """
    cleaned = clean_plain_text(raw_location)
    if cleaned is None:
        return None
    # Strip one or more trailing commas/semicolons and any whitespace
    # around them, e.g. "Success," -> "Success", "Foo , " -> "Foo".
    while cleaned and cleaned[-1] in ",;":
        cleaned = cleaned[:-1].rstrip()
    return cleaned or None


def _repair_swapped_salary_bounds(
    salary_min: int | None, salary_max: int | None, *, source_job_id: str
) -> tuple[int | None, int | None]:
    """Swap salary_min/salary_max if they arrived reversed.

    The database schema requires ``salary_max >= salary_min`` when both
    are present. A reversed pair is far more likely to be a source-side
    data-entry mistake than a meaningful "maximum below minimum" signal,
    so it's repaired here (and logged, so the correction is visible/
    auditable) rather than either silently kept broken or dropped
    entirely — dropping would lose real salary information over one
    swapped pair.
    """
    if salary_min is not None and salary_max is not None and salary_max < salary_min:
        logger.warning(
            "RemoteOK job {}: salary_min ({}) > salary_max ({}); swapping.",
            source_job_id,
            salary_min,
            salary_max,
        )
        return salary_max, salary_min
    return salary_min, salary_max


#: Minimum word count for a description to count as "substantial" in the
#: completeness score below. Chosen generously low (real job descriptions
#: typically run to several hundred words) specifically so this doesn't
#: double as a disguised spam filter — it only needs to distinguish
#: "basically no description" from "has one." Revisit once real
#: cross-source data exists to calibrate against (Phase 5).
_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20


def _compute_data_quality_score(
    *,
    salary_disclosed: bool,
    location_cleaned: str | None,
    skills: list[str],
    word_count: int,
) -> float:
    """Compute a 0.0-1.0 completeness score from already-cleaned fields.

    Deliberately measures completeness only — see the
    ``data_quality_score`` field docstring on ``CleanedJob`` for why this
    is not, and should not become, a spam/junk-content classifier. Four
    equally-weighted signals, each either present or not:
        - Is a salary disclosed?
        - Is a location specified?
        - Are there any skills/tags?
        - Is the description substantial (see
          ``_SUBSTANTIAL_DESCRIPTION_WORD_COUNT``) rather than empty or
          a single sentence?

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


class RemoteOKCleaner:
    """Cleans a batch of validated RemoteOK records into CleanedJob records."""

    def clean_job(self, raw_job: RawRemoteOKJob) -> CleanedJob:
        """Clean a single validated RemoteOK job record.

        Args:
            raw_job: A ``RawRemoteOKJob`` produced by ``RemoteOKParser``.

        Returns:
            The corresponding ``CleanedJob``.
        """
        salary_min, salary_max = _repair_swapped_salary_bounds(
            raw_job.salary_min, raw_job.salary_max, source_job_id=raw_job.source_job_id
        )
        description_clean = clean_html_text(raw_job.description_raw)
        location_cleaned = _clean_location(raw_job.location_raw)
        skills = _clean_tags(raw_job.tags)
        salary_disclosed = salary_min is not None or salary_max is not None
        word_count = len(description_clean.split()) if description_clean else 0

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
            apply_url=raw_job.apply_url,
            original_url=raw_job.original_url,
            posting_date=raw_job.posting_date,
            data_quality_score=_compute_data_quality_score(
                salary_disclosed=salary_disclosed,
                location_cleaned=location_cleaned,
                skills=skills,
                word_count=word_count,
            ),
            raw_payload=raw_job.raw_payload,
        )

    def clean_jobs(self, raw_jobs: list[RawRemoteOKJob]) -> list[CleanedJob]:
        """Clean a batch of validated RemoteOK job records.

        Mirrors ``RemoteOKParser.parse_jobs``'s skip-don't-crash philosophy:
        every input record already passed schema validation in Step 6, so a
        cleaning failure here is unexpected — but a single unexpected error
        (e.g. a pathological string that breaks the HTML parser) should
        still not take down the rest of an otherwise-healthy batch.

        Args:
            raw_jobs: Validated records from ``RemoteOKParser.parse_jobs()``.

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
                    "Unexpected error cleaning RemoteOK job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "RemoteOK cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
