"""Typed model for a single raw Reed job record.

Genuinely different from every other source's raw model, and why
-------------------------------------------------------------------
Every other ``Raw<Source>Job`` (``scrapers/remoteok/models.py``,
``scrapers/remotive/models.py``, ...) is built directly from ONE API
response shape via pydantic field aliases. ``RawReedJob`` cannot be, for a
structural reason confirmed live during scoping: Reed's Search endpoint
and its per-job Details endpoint return genuinely different field sets,
not one a strict subset of the other in a way aliasing alone could
resolve — Search reliably gives ``jobId``/``employerName``/``jobTitle``/
``locationName``/``jobUrl``/dates, but ``currency``/``salaryType``/
``contractType``/``fullTime``/``partTime``/``externalUrl`` were confirmed,
live, to come back ``null`` or absent from Search even for jobs whose
Details response had real values for all of them. So this model is built
via ``RawReedJob.from_combined()``, a classmethod that merges a Search
record with its Details record (assembled by ``pipeline.py`` — see that
module's docstring for why the merge decision happens there, not here),
preferring Details' value for any field both endpoints provide, rather
than via pydantic aliases on a single flat payload.

Deliberately NOT resolved into controlled vocabulary here, same principle
``RawRemoteOKJob``'s docstring states: ``contract_type_raw``/``full_time``/
``part_time``/``pay_period_raw`` are kept as Reed's own raw strings/
booleans. Mapping them onto ``ref.employment_types.code`` and the
``hourly``/``daily``/``weekly``/``monthly``/``yearly`` vocabulary is
``cleaning/reed_cleaner.py``'s job, not this model's — confirmed
mapping logic and precedence rules live there, next to
``CleanedJob`` construction, not duplicated here.

Reed's dates are ``DD/MM/YYYY`` strings (e.g. ``"18/09/2026"``) — confirmed
live, genuinely different from every other source's ISO-8601 dates
(RemoteOK, Remotive) — hence this module's own date parser rather than
reusing theirs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


def _parse_reed_date(value: object) -> datetime | None:
    """Parse a Reed ``DD/MM/YYYY`` date string into a UTC datetime.

    Returns ``None`` (rather than raising) for anything unparseable —
    same "a missing date is recoverable, a missing title/URL is not"
    reasoning ``RawRemoteOKJob._parse_posting_date`` documents.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value.strip(), "%d/%m/%Y")
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC)


class RawReedJob(BaseModel):
    """A single validated job record, merged from Reed's Search and Details responses.

    Attributes:
        source_job_id: Reed's ``jobId``, stringified. Present on both
            endpoints; Search's value is used (they're always identical
            for the same job — Details is fetched BY this ID).
        job_title: Reed's ``jobTitle``, raw and unmodified.
        company_name: Reed's ``employerName``, raw and unmodified.
        location_raw: Reed's ``locationName``.
        description_raw: Reed's ``jobDescription``. Details' value is
            preferred when available (confirmed live: Details returns the
            full HTML description; Search may return only a shorter
            excerpt) — see ``from_combined``.
        original_url: Reed's ``jobUrl`` — the canonical reed.co.uk posting
            page. Required, same "untraceable without a URL" reasoning
            every other source's raw model applies.
        apply_url: Reed's ``externalUrl`` (Details only — confirmed live,
            pointing at the employer's own ATS, e.g. Workday). ``None``
            when Details is absent for this job (a per-job Details fetch
            failure, or the job was deferred to a future run under
            ``ReedSettings.max_jobs_processed_per_run`` — see
            ``pipeline.py``) or wasn't provided.
        salary_min: Reed's ``minimumSalary``, at whatever cadence
            ``pay_period_raw`` describes (native, NOT annualized) — kept
            as ``float`` here since Reed sends decimal values (confirmed
            live, e.g. ``75000.0000``); ``cleaning/reed_cleaner.py``
            rounds to the ``int`` ``CleanedJob.salary_min`` requires.
        salary_max: Reed's ``maximumSalary``, same cadence/type notes as
            ``salary_min``.
        currency_iso_code: Reed's ``currency`` (Details only — confirmed
            live to come back as a plain ISO 4217 code, e.g. ``"GBP"``,
            needing no translation). ``None`` when Details is absent (see
            ``apply_url`` above) or the source itself didn't provide it
            (confirmed live: even Details can return ``currency: null``
            for a job with no disclosed salary at all).
        pay_period_raw: Reed's ``salaryType`` (Details only), e.g.
            ``"per annum"``, ``"per day"`` — confirmed live for those two
            specific values; ``"per hour"``/``"per week"``/``"per month"``
            are documented by Reed but not yet observed live. Left as
            Reed's own raw string; ``reed_cleaner.py`` maps it to the
            schema's ``hourly``/``daily``/``weekly``/``monthly``/``yearly``
            vocabulary and logs loudly on anything unrecognized.
        full_time: Reed's ``fullTime`` boolean (Details only).
        part_time: Reed's ``partTime`` boolean (Details only).
        contract_type_raw: Reed's ``contractType`` (Details only),
            e.g. ``"Permanent"`` — confirmed live to be Title Case, not
            the lowercase shown in Reed's own prose documentation.
        posting_date: Parsed from Details' ``datePosted`` if available,
            else Search's ``date`` — both are the same underlying value
            confirmed live (``"18/09/2026"`` in both places for the same
            job), so preferring one over the other doesn't lose anything;
            Details is preferred purely for consistency with every other
            field's preference rule.
        closing_date: Parsed from ``expirationDate`` (present on both
            endpoints with the same value, confirmed live).
        raw_payload: ``{"search": <raw search dict>, "details": <raw
            details dict, or None>}`` — both kept, not merged, per the
            platform's "never discard original source data" principle;
            Search and Details each carry a few fields the other doesn't
            (e.g. Search's ``employerProfileId``/``applications`` vs.
            Details' ``applicationCount``/``salary`` display string), so
            merging them into one dict would silently lose whichever
            field lost a naming collision.
    """

    source_job_id: str = Field(min_length=1)
    job_title: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    location_raw: str | None = None
    description_raw: str | None = None
    original_url: str = Field(min_length=1)
    apply_url: str | None = None
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    currency_iso_code: str | None = None
    pay_period_raw: str | None = None
    full_time: bool | None = None
    part_time: bool | None = None
    contract_type_raw: str | None = None
    posting_date: datetime | None = None
    closing_date: datetime | None = None
    raw_payload: dict = Field(default_factory=dict)

    @classmethod
    def from_combined(cls, search: dict, details: dict | None) -> RawReedJob:
        """Build a ``RawReedJob`` from a Search record and its optional Details record.

        Args:
            search: One raw entry from Reed Search's ``results`` list.
            details: The raw Reed Details response for this same job's
                ``jobId``. ``None`` is supported for testability, but in
                this pipeline's actual usage a job is only ever handed to
                this method once its Details fetch has succeeded — see
                ``pipeline.py``'s module docstring for why a per-job
                Details failure skips that job for the run entirely
                rather than reaching here with ``details=None``. When
                ``None``, every Details-only field
                (``currency_iso_code``, ``pay_period_raw``, ``full_time``,
                ``part_time``, ``contract_type_raw``, ``apply_url``)
                is left as ``None`` — an honest "we didn't check this
                time", not a guess.

        Raises:
            pydantic.ValidationError: If a required field (``source_job_id``,
                ``job_title``, ``company_name``, ``original_url``) is
                missing or empty in ``search`` — caught and logged by
                ``ReedParser``, same skip-don't-crash handling every
                other source's parser applies.
        """
        details = details or {}
        return cls(
            source_job_id=str(search.get("jobId", "")),
            job_title=search.get("jobTitle", "") or "",
            company_name=search.get("employerName", "") or "",
            location_raw=search.get("locationName"),
            # Details' description is the fuller one when present --
            # confirmed live (see module docstring); fall back to
            # Search's when Details wasn't fetched.
            description_raw=details.get("jobDescription") or search.get("jobDescription"),
            original_url=search.get("jobUrl", "") or "",
            apply_url=details.get("externalUrl"),
            salary_min=details.get("minimumSalary") or search.get("minimumSalary"),
            salary_max=details.get("maximumSalary") or search.get("maximumSalary"),
            currency_iso_code=details.get("currency") or search.get("currency"),
            pay_period_raw=details.get("salaryType"),
            full_time=details.get("fullTime"),
            part_time=details.get("partTime"),
            contract_type_raw=details.get("contractType"),
            posting_date=_parse_reed_date(details.get("datePosted") or search.get("date")),
            closing_date=_parse_reed_date(
                details.get("expirationDate") or search.get("expirationDate")
            ),
            raw_payload={"search": search, "details": details or None},
        )
