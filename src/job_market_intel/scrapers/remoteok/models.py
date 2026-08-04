"""Typed model for a single raw RemoteOK job record.

Why this model uses RemoteOK's own field meanings (not your database's
column names): this is explicitly the *raw, source-specific* shape of the
data, one step before cleaning/normalization. Step 8 (data cleaning) is
where raw fields get mapped onto your database's controlled vocabularies
(``ref.employment_types``, ``ref.locations``, etc.) — mixing that
responsibility into this model would make both steps harder to test and
reason about independently. Every other future scraper (Indeed, LinkedIn,
...) will have its own "Raw<Source>Job" model shaped around *that* source's
fields; the cleaning step is what makes them all comparable.

Field requirements below reflect what RemoteOK's public feed actually
returns: some fields (salary, location, tags) are frequently missing or
empty and are modeled as optional, matching your database's own treatment
of unknown/undisclosed data as a valid state rather than an error.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RawRemoteOKJob(BaseModel):
    """A single validated job record as returned by RemoteOK's JSON feed.

    Attributes:
        source_job_id: RemoteOK's own unique identifier for this posting
            (their ``id`` field). This is what your database's
            ``core.jobs.source_job_id`` will eventually store, paired with
            the RemoteOK ``source_id``, for deduplication.
        slug: RemoteOK's URL-friendly identifier for the posting.
        job_title: The raw, unmodified job title as RemoteOK lists it.
        company_name: The raw, unmodified employer name as RemoteOK lists
            it (company name resolution/deduplication happens later, in
            Step 23 — this is intentionally still the messy raw string).
        company_logo_url: URL to the company's logo image, if provided.
        tags: RemoteOK's own free-text tags (e.g. "python", "senior",
            "remote"). These are a mix of skills, seniority, and category
            hints — skill extraction (Step 24) will later decide what to
            do with them. Stored as-is here.
        location_raw: RemoteOK's raw, unparsed location/region string
            (e.g. "Worldwide", "USA Only"). Geographic normalization
            (Step 26) resolves this into ``ref.locations`` later.
        salary_min: Minimum of RemoteOK's advertised salary range, in USD,
            if disclosed. RemoteOK represents "no salary provided" as a
            literal ``0`` in its feed, not by omitting the field or
            sending ``null`` — that ``0`` is normalized to ``None`` here
            (see ``_coerce_zero_salary_to_none`` below) so every
            downstream consumer (batch validation, cleaning) can treat
            "salary is unknown" consistently as ``None``, without each
            one having to separately know about this RemoteOK-specific
            encoding quirk.
        salary_max: Maximum of RemoteOK's advertised salary range, in USD,
            if disclosed. Same ``0`` -> ``None`` normalization as
            ``salary_min``.
        description_raw: The full, unmodified job description as HTML or
            plain text (RemoteOK returns HTML). Cleaning/HTML-stripping
            happens in Step 8, not here.
        apply_url: The URL a candidate would use to apply. Falls back to
            ``original_url`` if RemoteOK does not provide a distinct apply
            link for this posting.
        original_url: The canonical URL of the job posting on RemoteOK.
            This is required — a job record with no URL at all cannot be
            traced back to its source and is not usable.
        posting_date: The UTC timestamp RemoteOK reports for when the job
            was posted, parsed from their raw ``date``/``epoch`` fields.
        raw_payload: The complete, unmodified raw dictionary for this job
            exactly as RemoteOK returned it. Kept for auditability —
            mirrors the design document's ``jobs.raw_html_ref`` philosophy
            of never discarding the original source data, even after it's
            been parsed into typed fields.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    source_job_id: str = Field(alias="id", min_length=1)
    slug: str | None = Field(default=None, alias="slug")
    job_title: str = Field(alias="position", min_length=1)
    company_name: str = Field(alias="company", min_length=1)
    company_logo_url: str | None = Field(default=None, alias="company_logo")
    tags: list[str] = Field(default_factory=list, alias="tags")
    location_raw: str | None = Field(default=None, alias="location")
    salary_min: int | None = Field(default=None, alias="salary_min", ge=0)
    salary_max: int | None = Field(default=None, alias="salary_max", ge=0)
    description_raw: str | None = Field(default=None, alias="description")
    apply_url: str | None = Field(default=None, alias="apply_url")
    original_url: str = Field(alias="url", min_length=1)
    posting_date: datetime | None = Field(default=None, alias="date")
    raw_payload: dict = Field(default_factory=dict, exclude=False)

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_missing_tags_to_empty_list(cls, value: object) -> list[str]:
        """RemoteOK sometimes omits ``tags`` entirely rather than sending an empty list."""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(tag) for tag in value]
        return []

    @field_validator("posting_date", mode="before")
    @classmethod
    def _parse_posting_date(cls, value: object) -> datetime | None:
        """Parse RemoteOK's date string into a timezone-aware UTC datetime.

        RemoteOK's ``date`` field is typically an ISO-8601 string (e.g.
        ``"2026-01-15T09:00:00+00:00"``). This validator accepts that
        format and returns ``None`` (rather than raising) for anything
        unparseable, so a single malformed date doesn't reject an
        otherwise-valid job record — a missing posting date is recoverable
        downstream (it can be re-derived from ``first_scraped_at``), while
        a missing job title or URL is not.
        """
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return None

    @field_validator("salary_min", "salary_max", mode="after")
    @classmethod
    def _coerce_zero_salary_to_none(cls, value: int | None) -> int | None:
        """Treat RemoteOK's literal ``0`` salary as "not disclosed", not "pays $0".

        Observed live: RemoteOK's feed sends ``"salary_min": 0`` (and/or
        ``salary_max: 0``) for postings where no real salary figure was
        entered, rather than omitting the field. Left as literal ``0``,
        this silently corrupts every downstream consumer that checks
        "is salary present?" via `is not None` (the batch validator's
        missing-field rate, and the cleaner's completeness score both do
        exactly this) — ``0`` is not ``None``, so both would wrongly
        conclude a salary was disclosed.

        A genuine $0 salary is not a realistic value for the professional/
        technical remote jobs this feed lists, so normalizing literal
        ``0`` to ``None`` here carries effectively no risk of discarding
        real data, while fixing the corruption at its single source rather
        than requiring every downstream consumer to independently know
        about this RemoteOK-specific quirk.
        """
        return None if value == 0 else value
