"""Typed model for a single raw Remotive job record.

Mirrors the role ``scrapers/remoteok/models.py`` and
``scrapers/weworkremotely/models.py`` play for their sources: this is the
raw, source-specific shape of the data, one step before cleaning
(``cleaning/remotive_cleaner.py``) maps it onto the shared ``CleanedJob``
contract.

Confirmed while investigating Step 18 (official ``remotive-com/remote-jobs-api``
GitHub README, cross-checked against several independent third-party
scrapers built on the live API — the endpoint requires no auth and returns
no browser-friendly page, so it could not be fetched directly through this
project's own tooling; the README is the primary source, not an assumption):

    - Endpoint: ``GET https://remotive.com/api/remote-jobs`` — note the
      domain. The older ``remotive.io`` endpoint referenced in some dated
      third-party writeups is retired.
    - The top-level response is a **dict**, not a bare list like
      RemoteOK's (``{"job-count": N, "jobs": [...]}``) — ``client.py``
      checks for this shape, not RemoteOK's list shape.
    - No pagination: one call returns every currently-active listing.
      Same "single feed, no pages" shape as We Work Remotely's RSS.
    - ``id`` is a genuine stable numeric identifier (unlike WWR, which has
      none at all and needs a URL-slug workaround) — used directly as
      ``source_job_id``.
    - ``publication_date`` is ISO-8601 (like RemoteOK's ``date``), not
      WWR's RFC 822 — ``datetime.fromisoformat`` is sufficient, no new
      date-parsing logic needed.
    - ``salary`` is a **free-text string** (e.g. ``"$40,000 - $50,000"``,
      ``"$65k+"``, ``"Competitive"``, or empty) — genuinely different from
      RemoteOK's structured ``salary_min``/``salary_max`` integers and from
      WWR's total absence of any salary field. ``_parse_salary_range``
      below extracts a numeric USD range ONLY when the text is an
      unambiguous ``"$X - $Y"``-shaped pattern; anything else (a single
      figure, "+", "DOE", "Competitive", non-USD symbols, empty) is left
      as ``None``/``None`` rather than guessed at. This is a deliberately
      conservative scope decision, agreed before writing this code:
      extracting a number from free text is adjacent to the NLP-driven
      skill/salary-standardization work planned for Phase 5, and a wrong
      guess here would silently corrupt ``data_quality_score`` and any
      downstream salary analysis; an honestly-missing value does not.
    - ``tags``: the official README's own example response does NOT show
      a ``tags`` field, but every independently-built third-party scraper
      inspected while investigating this step reports one being present
      on the live API (a skills/keyword list, matching RemoteOK's own
      ``tags`` in spirit). Modeled here as optional, defaulting to an
      empty list if genuinely absent, so this scraper works correctly
      either way — but this is flagged explicitly as something to
      confirm against this project's own first real live run (per the
      project's "verify against the real environment" discipline), not
      something taken on faith from either source.
    - No explicit posting-expiration field (unlike WWR's ``expires_at``)
      — ``closing_date`` stays ``None`` for every Remotive job, same
      honest gap as RemoteOK.

Field requirements below reflect the officially documented shape; the
``tags`` uncertainty above is the one point still pending live
confirmation.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Matches an unambiguous "$X - $Y" (or "$Xk - $Yk") USD range. Deliberately
#: narrow — see the module docstring's ``salary`` bullet for why a single
#: figure, a "+"-suffixed floor, non-USD symbols, or free text like
#: "Competitive"/"DOE" are intentionally NOT matched and fall through to
#: (None, None) rather than being guessed at.
_SALARY_RANGE_PATTERN = re.compile(
    r"^\$\s*([\d,]+)\s*([kK])?\s*(?:-|–|to)\s*\$?\s*([\d,]+)\s*([kK])?\s*$"
)


def _parse_salary_range(raw_salary: str | None) -> tuple[int | None, int | None]:
    """Extract a numeric (min, max) USD range from Remotive's free-text salary field.

    Returns (None, None) for anything that isn't an unambiguous
    "$X - $Y"-shaped string — see the module docstring for the full
    rationale. Never raises; a field this loosely specified by the source
    must never be able to fail an otherwise-valid job record.

    Ordering: the two numbers are matched purely by position in the
    string ("first number", "second number"), not by which one is
    actually smaller — Remotive's free text isn't guaranteed to write
    the lower figure first. A real production example: a raw ``salary``
    value that parsed to (312000, 52000) positionally, which is a valid
    salary pair just written high-to-low, not a malformed one. If the
    parsed pair comes back with the first number larger than the second,
    it's swapped here so the caller always receives (min, max) with
    min <= max — confirmed by testing against the real database's
    ``ck_job_salaries_normalized_range``/``ck_job_salaries_range``
    constraints, which reject min > max outright.
    """
    if not raw_salary or not raw_salary.strip():
        return None, None

    match = _SALARY_RANGE_PATTERN.match(raw_salary.strip())
    if not match:
        return None, None

    low_digits, low_k, high_digits, high_k = match.groups()

    def _to_int(digits: str, k_suffix: str | None) -> int:
        value = int(digits.replace(",", ""))
        return value * 1000 if k_suffix else value

    first_value = _to_int(low_digits, low_k)
    second_value = _to_int(high_digits, high_k)

    if first_value > second_value:
        return second_value, first_value
    return first_value, second_value


class RawRemotiveJob(BaseModel):
    """A single validated job record as returned by Remotive's JSON API.

    Attributes:
        source_job_id: Remotive's own numeric ``id``, stringified for
            consistency with every other source's ``source_job_id: str``
            (see ``validation/common.py``'s ``HasSourceJobId`` protocol).
        job_title: The raw, unmodified job title.
        company_name: The raw, unmodified employer name. Canonical
            company resolution is a later, separate step (Step 25), same
            as every other source.
        company_logo_url: URL to the company's logo image, from
            Remotive's ``company_logo`` field. Not every posting includes
            one.
        category_raw: Remotive's own job-category label (e.g. "Software
            Development"). Raw hint; resolving this onto
            ``ref.job_categories`` is a later normalization step, same
            treatment as WWR's ``category_raw``.
        employment_type_raw: Remotive's ``job_type`` label (e.g.
            "full_time", "contract"). Often blank on the live feed per
            the official docs. Raw hint, not yet resolved.
        location_raw: Remotive's ``candidate_required_location`` string
            (e.g. "USA", "Worldwide"). Unparsed, same treatment as
            RemoteOK's single ``location`` string.
        tags: Remotive's skill/keyword list, if the live API sends one —
            see the module docstring's ``tags`` bullet. Defaults to an
            empty list rather than failing the record if absent.
        salary_min: Parsed from Remotive's free-text ``salary`` field
            ONLY when it is an unambiguous "$X - $Y" range — see
            ``_parse_salary_range``. ``None`` otherwise, including when
            ``salary`` has text that just isn't parseable.
        salary_max: Paired with ``salary_min``, same parsing rule.
        description_raw: The full, unmodified job description as HTML.
            Cleaning/HTML-stripping happens in the cleaner, not here.
        original_url: The canonical URL of the job posting on Remotive
            (Remotive's ``url``). Required — a job record with no URL
            cannot be traced back to its source.
        posting_date: The timestamp Remotive reports for when the job was
            posted, parsed from ``publication_date``'s ISO-8601 format.
        raw_payload: The complete, unmodified raw dictionary for this job
            exactly as ``RemotiveClient`` extracted it from the API
            response. Kept for auditability, same principle as every
            other source.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    source_job_id: str = Field(alias="id", min_length=1)
    job_title: str = Field(alias="title", min_length=1)
    company_name: str = Field(alias="company_name", min_length=1)
    company_logo_url: str | None = Field(default=None, alias="company_logo")
    category_raw: str | None = Field(default=None, alias="category")
    employment_type_raw: str | None = Field(default=None, alias="job_type")
    location_raw: str | None = Field(default=None, alias="candidate_required_location")
    tags: list[str] = Field(default_factory=list, alias="tags")
    salary_min: int | None = Field(default=None)
    salary_max: int | None = Field(default=None)
    description_raw: str | None = Field(default=None, alias="description")
    original_url: str = Field(alias="url", min_length=1)
    posting_date: datetime | None = Field(default=None, alias="publication_date")
    raw_payload: dict = Field(default_factory=dict, exclude=False)

    @field_validator("source_job_id", mode="before")
    @classmethod
    def _stringify_id(cls, value: object) -> str:
        """Coerce Remotive's numeric ``id`` into the ``str`` every source's ``source_job_id`` uses.

        Remotive's ``id`` is a genuine integer (unlike WWR, which has no
        numeric ID at all) — this validator only changes its Python type
        for consistency with ``HasSourceJobId``/the database schema's
        ``TEXT source_job_id`` column, it doesn't derive or reshape
        anything the way WWR's slug-extraction does.
        """
        if value is None:
            raise ValueError("id/source_job_id must not be null")
        text = str(value).strip()
        if not text:
            raise ValueError("id/source_job_id must not be empty")
        return text

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: object) -> list[str]:
        """Accept a list, a comma-separated string, or a missing field, uniformly.

        See the module docstring's ``tags`` bullet: the live shape of
        this field is not yet confirmed with certainty, so this accepts
        either a JSON list (RemoteOK's ``tags`` shape) or, defensively, a
        comma-separated string (WWR's ``skills`` shape) rather than
        assuming one specific shape and failing records if reality
        turns out to be the other.
        """
        if value is None:
            return []
        if isinstance(value, list):
            return [str(entry) for entry in value]
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return []

    @field_validator("posting_date", mode="before")
    @classmethod
    def _parse_iso_date(cls, value: object) -> datetime | None:
        """Parse Remotive's ISO-8601 ``publication_date`` into a timezone-aware UTC datetime.

        Mirrors ``RawRemoteOKJob``'s own ISO-8601 handling (both sources
        use the same format, confirmed against the official docs) rather
        than WWR's RFC 822 parser, which would not apply here. Returns
        ``None`` (rather than raising) for anything unparseable, same
        skip-don't-crash philosophy every other source's date handling
        follows — a missing posting date is recoverable downstream, a
        missing job title or URL is not.
        """
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        return None

    @model_validator(mode="before")
    @classmethod
    def _parse_salary_field(cls, data: object) -> object:
        """Parse Remotive's free-text ``salary`` field into structured bounds.

        Mirrors ``RawWWRJob._split_company_and_title``'s pattern exactly:
        a ``model_validator(mode="before")`` runs ahead of per-field
        validation because ``salary_min``/``salary_max`` have no
        source-side alias to key off of — there is no such field in
        Remotive's payload, only ``salary``, a differently-named free-text
        field entirely. Keeping the actual parsing logic in the standalone
        ``_parse_salary_range`` function (rather than inline here) keeps
        that logic independently testable.

        If ``salary_min``/``salary_max`` are already present in the input
        (e.g. a test constructing a ``RawRemotiveJob`` directly), this is
        a no-op — explicit values win and no parse is attempted, same
        "explicit wins" rule WWR's title-splitting validator follows.
        """
        if not isinstance(data, dict):
            return data
        if "salary_min" in data or "salary_max" in data:
            return data
        raw_salary = data.get("salary")
        if isinstance(raw_salary, str):
            parsed_min, parsed_max = _parse_salary_range(raw_salary)
            data = {**data, "salary_min": parsed_min, "salary_max": parsed_max}
        return data
