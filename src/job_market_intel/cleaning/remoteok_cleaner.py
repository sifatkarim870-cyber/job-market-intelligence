"""Cleans validated RemoteOK records into standardized, storage-ready records.

Where this fits: ``scrapers/remoteok/parser.py`` (Step 6) validates that a
record has the right *shape* (required fields present, right types). This
module takes that validated-but-still-messy ``RawRemoteOKJob`` and produces
a ``CleanedRemoteOKJob`` — text fixed (encoding, HTML entities, HTML tags,
whitespace), obvious data-entry mistakes repaired (swapped salary bounds),
and a couple of fields pre-derived that the database schema itself expects
(``salary_disclosed``, ``word_count``).

What this deliberately does NOT do — these are later, separate steps, and
mixing them in here would blur boundaries the rest of this codebase has
been careful to keep sharp:
    - Resolve ``company_name`` to a canonical ``core.companies`` row
      (Step 23 — company resolution needs fuzzy matching across MULTIPLE
      sources, which doesn't exist yet with only RemoteOK live).
    - Resolve ``location_cleaned`` to a ``ref.locations`` row (Step 26 —
      geographic normalization).
    - Extract structured skills from ``tags``/``description_clean``
      (Step 24 — skill extraction).
    - Convert/normalize currency (Step 25 — RemoteOK salaries are already
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

from datetime import datetime

from loguru import logger
from pydantic import BaseModel

from job_market_intel.scrapers.remoteok.models import RawRemoteOKJob

from .text_utils import clean_html_text, clean_plain_text


class CleanedRemoteOKJob(BaseModel):
    """A RemoteOK job record after text cleaning and light standardization.

    Attributes:
        source_job_id: Unchanged from ``RawRemoteOKJob`` — this is an
            identifier, not display text, so there is nothing to clean.
        job_title: Cleaned (entities decoded, mojibake fixed, whitespace
            normalized).
        company_name: Cleaned the same way. Still the raw employer name as
            RemoteOK spells it — canonical company resolution is Step 23.
        company_logo_url: Unchanged (a URL is either usable as-is or not;
            "cleaning" doesn't apply).
        tags: Each tag cleaned, lowercased (skills/tag matching downstream
            is expected to be case-insensitive), stripped of empties, and
            de-duplicated while preserving first-seen order.
        location_cleaned: The raw location string with text cleaned and a
            RemoteOK-specific quirk fixed: a stray trailing comma left
            over when RemoteOK omits the country half of a "City, Country"
            pair (observed live as e.g. ``"Success,"``, ``"Mangalagiri,"``).
            Still a free-text string — resolving this to ``ref.locations``
            is Step 26.
        salary_min: Cleaned salary lower bound. Swapped with
            ``salary_max`` if the source had them reversed (see
            ``_repair_swapped_salary_bounds``); otherwise unchanged.
        salary_max: See ``salary_min``.
        salary_disclosed: ``True`` if either salary bound is present.
            Pre-derived here because it maps directly onto
            ``salary.job_salaries.salary_disclosed`` in the schema, and
            computing it once, consistently, beats every downstream
            consumer re-deriving "is salary present" from two nullable
            fields.
        description_clean: The HTML description with tags stripped,
            entities decoded, mojibake fixed, and whitespace normalized.
            Maps onto ``core.job_descriptions.description_clean``.
        word_count: Word count of ``description_clean``. Maps onto
            ``core.job_descriptions.word_count``.
        apply_url: Unchanged.
        original_url: Unchanged.
        posting_date: Unchanged — a missing/unparseable date is not
            something text-cleaning can recover; it stays ``None`` if the
            parser already couldn't determine it.
        data_quality_score: A 0.0-1.0 completeness score — maps directly
            onto ``core.jobs.data_quality_score`` in the schema, described
            there as a "completeness/confidence score, useful ML/QA
            feature." Deliberately measures COMPLETENESS only (is a
            salary present? a location? tags? a substantial description?)
            — not an attempt to detect spam/junk listings by their
            content. RemoteOK is known to mix low-value promotional
            listings in among real postings, and those listings do tend
            to score low here as a natural side effect of being sparse —
            but that's an observed correlation, not the design goal.
            Building an actual junk-content classifier would mean writing
            rules fitted to one source's quirks with no second source yet
            to check them against; that's explicitly deferred to Phase 5,
            once there's enough cross-source data to calibrate against
            without just guessing.
        raw_payload: Carried forward unchanged from the raw record, per
            the platform's "never discard original source data" principle
            (mirrors ``jobs.raw_html_ref`` in the schema design).
    """

    source_job_id: str
    job_title: str
    company_name: str
    company_logo_url: str | None
    tags: list[str]
    location_cleaned: str | None
    salary_min: int | None
    salary_max: int | None
    salary_disclosed: bool
    description_clean: str | None
    word_count: int
    apply_url: str | None
    original_url: str
    posting_date: datetime | None
    data_quality_score: float
    raw_payload: dict


def _clean_tags(raw_tags: list[str]) -> list[str]:
    """Clean, lowercase, and de-duplicate a list of tags, preserving first-seen order.

    Lowercasing is applied because tag/skill matching downstream (Step 24)
    is expected to be case-insensitive, matching ``ref.skills.normalized_skill_name``'s
    own lowercased convention in the schema. The original casing is not
    lost — it still lives in ``raw_payload``.
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
    tags: list[str],
    word_count: int,
) -> float:
    """Compute a 0.0-1.0 completeness score from already-cleaned fields.

    Deliberately measures completeness only — see the
    ``data_quality_score`` field docstring on ``CleanedRemoteOKJob`` for
    why this is not, and should not become, a spam/junk-content
    classifier. Four equally-weighted signals, each either present or
    not:
        - Is a salary disclosed?
        - Is a location specified?
        - Are there any tags?
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
        len(tags) > 0,
        word_count >= _SUBSTANTIAL_DESCRIPTION_WORD_COUNT,
    ]
    return round(sum(signals) / len(signals), 2)


class RemoteOKCleaner:
    """Cleans a batch of validated RemoteOK records into standardized records."""

    def clean_job(self, raw_job: RawRemoteOKJob) -> CleanedRemoteOKJob:
        """Clean a single validated RemoteOK job record.

        Args:
            raw_job: A ``RawRemoteOKJob`` produced by ``RemoteOKParser``.

        Returns:
            The corresponding ``CleanedRemoteOKJob``.
        """
        salary_min, salary_max = _repair_swapped_salary_bounds(
            raw_job.salary_min, raw_job.salary_max, source_job_id=raw_job.source_job_id
        )
        description_clean = clean_html_text(raw_job.description_raw)
        location_cleaned = _clean_location(raw_job.location_raw)
        tags = _clean_tags(raw_job.tags)
        salary_disclosed = salary_min is not None or salary_max is not None
        word_count = len(description_clean.split()) if description_clean else 0

        return CleanedRemoteOKJob(
            source_job_id=raw_job.source_job_id,
            job_title=clean_plain_text(raw_job.job_title) or raw_job.job_title,
            company_name=clean_plain_text(raw_job.company_name) or raw_job.company_name,
            company_logo_url=raw_job.company_logo_url,
            tags=tags,
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
                tags=tags,
                word_count=word_count,
            ),
            raw_payload=raw_job.raw_payload,
        )

    def clean_jobs(self, raw_jobs: list[RawRemoteOKJob]) -> list[CleanedRemoteOKJob]:
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
        cleaned_jobs: list[CleanedRemoteOKJob] = []
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
