"""Source-agnostic cleaned-job contract shared by every scraper's cleaner.

Where this fits: each source gets its own ``Raw<Source>Job`` model
(``scrapers/<source>/models.py``) shaped around that source's own field
names and quirks, and its own ``<Source>Cleaner`` (``cleaning/<source>_cleaner.py``)
that knows how to turn one into the other. What every one of those cleaners
must agree on, no matter how different the source, is what comes *out* the
other end — a single, storage-ready shape that ``db.job_repository`` (and,
later, normalization/skill-extraction steps) can consume without needing to
know which of the ~50 planned scrapers a given record originated from.
``CleanedJob`` is that shape.

This mirrors the same reasoning already applied to ``text_utils.py``: the
*problem* every cleaner solves (produce a storage-ready record with
consistent field names and pre-derived flags) is fully known today, even
though only one source (RemoteOK) exists yet to instantiate it — unlike a
scraper base class, whose shape would have to be guessed from a single
example (see ``scrapers/`` package docstrings), a cleaned-record contract's
shape is dictated by the database schema itself, which is already fixed.

Field naming note: this model calls the tag/skill list ``skills``, not
``tags``. RemoteOK's raw feed calls it ``tags``, and some future sources
may too — but the database schema's vocabulary is ``ref.skills`` /
``bridge.job_skills``, and every downstream consumer should be able to read
``skills`` on any ``CleanedJob`` without needing to remember that one
particular source called it something else. Each source's cleaner is
responsible for mapping its own field name onto ``skills`` at the boundary;
callers of this module never see the source-specific name.

What this model deliberately does NOT do — these stay later, separate
steps for the same reasons ``remoteok_cleaner.py`` documents in its own
module docstring, now generalized to every future source:
    - Resolve ``company_name`` to a canonical ``core.companies`` row
      (Step 25 — company resolution).
    - Resolve ``location_cleaned`` to a ``ref.locations`` row (Step 28 —
      geographic normalization).
    - Extract structured skills from ``skills``/``description_clean``
      into ``ref.skills`` rows (Step 26 — skill extraction).
    - Convert/normalize currency (Step 27 — salary standardization).
    - Compute ``content_hash`` (tied to database insert/update logic in
      ``db.job_repository``, not cleaning).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CleanedJob(BaseModel):
    """A job record after source-specific text cleaning and light standardization.

    Every field here maps directly onto a schema column (see
    ``job_market_intelligence_schema.sql``), so a source's cleaner is
    finished once it can populate this model — it should not need to know
    anything about how the record gets persisted.

    Attributes:
        source_job_id: The source's own identifier for this posting,
            unchanged — an identifier, not display text, so there is
            nothing to clean.
        job_title: Cleaned (entities decoded, mojibake fixed, whitespace
            normalized).
        company_name: Cleaned the same way. Still the raw employer name as
            the source spells it — canonical company resolution is a
            later, separate step (Step 25).
        company_logo_url: Unchanged (a URL is either usable as-is or not;
            "cleaning" doesn't apply).
        skills: Cleaned, lowercased, de-duplicated skill/tag strings from
            the source (e.g. RemoteOK's ``tags``). Still free-text at this
            point — resolving these onto ``ref.skills`` rows is Step 26.
            Named ``skills`` (not each source's own term for the same
            concept) to match the schema's vocabulary; see the module
            docstring for why.
        location_cleaned: The raw location string with text cleaned and
            any source-specific quirks fixed. Still a free-text string —
            resolving this to ``ref.locations`` is Step 28.
        salary_min: Cleaned salary lower bound, in the source's original
            currency. Swapped with ``salary_max`` if the source had them
            reversed; otherwise unchanged.
        salary_max: See ``salary_min``.
        salary_disclosed: ``True`` if either salary bound is present.
            Pre-derived here because it maps directly onto
            ``salary.job_salaries.salary_disclosed`` in the schema, and
            computing it once, consistently, per source, beats every
            downstream consumer re-deriving "is salary present" from two
            nullable fields.
        description_clean: The description with markup stripped, entities
            decoded, mojibake fixed, and whitespace normalized. Maps onto
            ``core.job_descriptions.description_clean``.
        word_count: Word count of ``description_clean``. Maps onto
            ``core.job_descriptions.word_count``.
        apply_url: Unchanged.
        original_url: Unchanged.
        posting_date: Unchanged — a missing/unparseable date is not
            something text-cleaning can recover; it stays ``None`` if the
            source's parser already couldn't determine it.
        closing_date: Unchanged — maps onto ``core.jobs.closing_date`` in
            the schema. Defaults to ``None`` since not every source
            provides an expiration date (RemoteOK's feed never has;
            We Work Remotely's does, via its ``<expires_at>`` element) —
            optional with a default so adding this field didn't require
            touching every existing cleaner that has no such date to give.
        data_quality_score: A 0.0-1.0 completeness score — maps directly
            onto ``core.jobs.data_quality_score`` in the schema. Measures
            completeness only (is a salary present? a location? skills? a
            substantial description?), never content judgment (e.g. spam
            detection) — see ``remoteok_cleaner.py`` for the fuller
            rationale, which applies to every source equally.
        raw_payload: Carried forward unchanged from the raw record, per
            the platform's "never discard original source data" principle
            (mirrors ``jobs.raw_html_ref`` in the schema design).
        currency_iso_code: ISO 4217 code (e.g. ``"USD"``, ``"GBP"``) for
            ``salary_min``/``salary_max``, as reported (or, for a source
            that doesn't report one at all, assumed) by THIS record's own
            source -- not by ``db.job_repository``. Required, not
            optional: every cleaner must state its assumption explicitly
            rather than leaving a gap for the repository to fill in. Maps
            onto ``salary.job_salaries.currency_id`` via a
            ``ref.currencies`` lookup. Added when the Reed scraper needed
            a real per-record currency instead of the previously
            hardcoded ``"USD"`` -- see ``db.job_repository``'s module
            docstring for the fuller "Reed scraper note".
        pay_period: One of ``hourly``/``daily``/``weekly``/``monthly``/``yearly``,
            matching ``salary.job_salaries.pay_period``'s CHECK constraint.
            Same rationale and history as ``currency_iso_code`` above --
            this is the field whose previous hardcoding (always
            ``"yearly"``) is Step 27's documented bug pattern; Reed is
            the first source that reports pay period per-record instead
            of needing it assumed.
        employment_type_code: One of ``ref.employment_types.code``'s
            values (``full_time``/``part_time``/``contract``/``temporary``/
            ``internship``/``freelance``/``apprenticeship``), or ``None``
            if the source doesn't report an employment type at all
            (RemoteOK, Remotive, and We Work Remotely all leave this
            ``None`` today -- an honest absence, not a guess). Maps onto
            ``core.jobs.employment_type_id`` via a ``ref.employment_types``
            lookup -- the first field any source has populated there;
            previously always written as ``NULL`` regardless of source.
    """

    source_job_id: str
    job_title: str
    company_name: str
    company_logo_url: str | None
    skills: list[str]
    location_cleaned: str | None
    salary_min: int | None
    salary_max: int | None
    salary_disclosed: bool
    description_clean: str | None
    word_count: int
    apply_url: str | None
    original_url: str
    posting_date: datetime | None
    closing_date: datetime | None = None
    data_quality_score: float
    raw_payload: dict
    currency_iso_code: str
    pay_period: str
    employment_type_code: str | None = None
