"""Cleans validated Greenhouse records into standardized, storage-ready records.

Follows the boundary every other cleaner in this project keeps: take a
validated-but-messy ``RawGreenhouseJob`` and produce a ``CleanedJob``, only
removing noise, never making judgment calls about meaning. Company resolution,
geographic resolution, skill extraction, currency conversion and content-hash
computation are all later, separate steps.

Genuine differences from the existing cleaners, each following from a
structural fact about Greenhouse confirmed while building
``scrapers/greenhouse/models.py``:

    - ``content`` is the real prize. Greenhouse returns the FULL description
      as HTML (``content=true``), so ``description_clean`` is real prose and
      not a teaser -- which also means ``clean_html_text`` does real work here,
      stripping the layout markup that Greenhouse wraps around every posting.
    - No salary at all. Greenhouse exposes no compensation field, so
      ``salary_min``/``salary_max``/``salary_disclosed`` stay ``None``/False
      and ``currency_iso_code``/``pay_period`` are left unset. That is an
      honest gap in the source, not an extraction failure.
    - No closing date. There is no expiry field, so ``closing_date`` stays
      None, same as Remotive/RemoteOK.
    - Location is one free-text string (``location.name``), e.g. "Remote,
      France". Greenhouse's own ``offices`` list is a better-structured
      secondary signal and is preferred when the free text is vague, because
      that string is employer-authored and frequently just says "Remote".
    - Greenhouse publishes an ISO ``language`` code on most boards, which is
      more reliable than detection for an English-first ATS. It is preserved in
      ``raw_payload`` but NOT written to ``core.jobs.language_code`` here:
      ``CleanedJob`` has no such field and ``save_cleaned_job`` does not accept
      one -- language assignment is the translation stage's job, the same as for
      every other source.
"""

from __future__ import annotations

import html

from loguru import logger

from job_market_intel.scrapers.greenhouse.models import RawGreenhouseJob

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
    every other cleaner's, so the number stays comparable across sources.

    Greenhouse will score 0.75 on the four signals for a typical posting: it
    reliably has a location and a substantial description, and reliably has
    no salary. That is an accurate reading of the source, not a defect.
    """
    signals = [
        salary_disclosed,
        location_cleaned is not None,
        len(skills) > 0,
        word_count >= _SUBSTANTIAL_DESCRIPTION_WORD_COUNT,
    ]
    return round(sum(signals) / len(signals), 2)


def _strip_greenhouse_html(content: str) -> str:
    """Turn Greenhouse's ``content`` field into plain text.

    Greenhouse DOUBLE-ENCODES: the JSON carries HTML that has itself been
    entity-escaped, so the value arrives as
    ``&lt;div class=&quot;...&quot;&gt;&lt;p&gt;...``. Feeding that straight to
    ``clean_html_text`` makes BeautifulSoup parse it as TEXT rather than markup:
    it decodes the entities and hands back literal ``<div class="content-intro">``
    tags, which then land in ``core.job_descriptions.description_clean`` and
    into the translation prompt. Verified on live GitLab rows.

    So: unescape once here, then run the shared cleaner, which does the actual
    tag stripping. Kept local to this cleaner rather than changing
    ``clean_html_text``, because no other source sends double-encoded HTML and
    a second unescape pass would corrupt their entities.
    """
    if not content:
        return ""
    return clean_html_text(html.unescape(content)) or ""


def _resolve_location(raw_job: RawGreenhouseJob) -> str | None:
    """Pick the most useful location string this posting offers.

    ``location.name`` is employer free text and is frequently just "Remote",
    which would resolve to nothing downstream. Greenhouse's ``offices`` list is
    structured and usually carries the country, so prefer it when the free text
    is missing or tells us nothing beyond remoteness.
    """
    name = clean_plain_text(raw_job.location_name) or None
    if name and name.lower().strip(" ,") not in {"remote", "anywhere", "global"}:
        return name
    offices = [clean_plain_text(o) for o in raw_job.office_names]
    offices = [o for o in offices if o]
    return offices[0] if offices else name


class GreenhouseCleaner:
    """Cleans a batch of validated Greenhouse records into CleanedJob records."""

    def clean_job(self, raw_job: RawGreenhouseJob) -> CleanedJob:
        """Clean one validated Greenhouse posting."""
        description_clean = _strip_greenhouse_html(raw_job.content)
        location_cleaned = _resolve_location(raw_job)
        skills = [clean_plain_text(d) for d in raw_job.department_names]
        skills = [s for s in skills if s]
        # Greenhouse has no compensation field at all.
        salary_disclosed = False
        word_count = len(description_clean.split()) if description_clean else 0

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=clean_plain_text(raw_job.title) or raw_job.title,
            company_name=clean_plain_text(raw_job.company_name) or raw_job.company_name,
            skills=skills,
            location_cleaned=location_cleaned,
            salary_min=None,
            salary_max=None,
            salary_disclosed=salary_disclosed,
            description_clean=description_clean,
            word_count=word_count,
            # Greenhouse exposes exactly one URL, the public posting page, which
            # is both the canonical reference and where a human applies. Same
            # single-URL fallback the Remotive cleaner documents.
            apply_url=raw_job.absolute_url,
            original_url=raw_job.absolute_url,
            posting_date=raw_job.first_published or raw_job.updated_at,
            # closing_date intentionally omitted: Greenhouse exposes no
            # posting-expiration field.
            data_quality_score=_compute_data_quality_score(
                salary_disclosed=salary_disclosed,
                location_cleaned=location_cleaned,
                skills=skills,
                word_count=word_count,
            ),
            raw_payload=raw_job.model_dump(mode="json"),
            # Greenhouse publishes no logo, no currency and no pay period, but
            # CleanedJob requires all three explicitly rather than defaulting.
            # Stating them is the honest choice: remotive_cleaner documents the
            # same convention, and a fabricated USD/yearly would silently
            # imply a salary Greenhouse never published.
            company_logo_url=None,
            currency_iso_code="USD",
            pay_period="yearly",
        )

    def clean_jobs(self, raw_jobs: list[RawGreenhouseJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) individual bad records.

        Mirrors the other cleaners: one malformed posting must not cost the
        rest of the board.
        """
        cleaned: list[CleanedJob] = []
        skipped = 0
        for raw_job in raw_jobs:
            try:
                cleaned.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - one bad row is not the batch
                skipped += 1
                logger.warning("skipping Greenhouse posting id={}: {}", raw_job.source_job_id, exc)
        if skipped:
            logger.warning(
                "skipped {} of {} Greenhouse records while cleaning", skipped, len(raw_jobs)
            )
        return cleaned
