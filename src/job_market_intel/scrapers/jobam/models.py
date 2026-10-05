"""Typed model for a single raw Job.am job record.

Mirrors the role ``scrapers/myjob/models.py`` plays for MyJob.mu: the
raw, source-specific shape, one step before
``cleaning/jobam_cleaner.py`` maps it onto the shared ``CleanedJob``.

Where each field comes from (confirmed live, 2026-10-05)
--------------------------------------------------------
job.am exposes two payload shapes that are merged by ``client.py``:

* **List** — ``GET https://job.am/api/jobs`` returns the entire board
  as one bare JSON array (~1,136 items; pagination params are ignored).
  Each item has exactly these keys: ``Id`` (int), ``Title``, ``Company``,
  ``Url`` (public job page), ``Logo``, ``DeadLine`` (ASP.NET MS JSON
  date, ``/Date(1793764070000)/``), ``Location`` (board display value —
  usually the city in Armenian, e.g. ``Երևան``), ``IndustryId`` and
  ``IndustryIds``. No posting date, no description, no employment type,
  no salary anywhere in the list payload.
* **Detail** — the job's public page carries a schema.org
  ``JobPosting`` JSON-LD block whose keys are ``datePosted``
  (``"2026-10-05"``), ``validThrough`` (deadline, same ISO shape),
  ``description`` (plain text), ``employmentType`` (observed values:
  "Full Time", "Part Time", "Full Time, Part Time", "Flexible",
  "Part Time, Flexible", "Full Time, Flexible", "Contract"),
  ``hiringOrganization {name, logo}`` and
  ``jobLocation.address {addressLocality, addressCountry}``. The client
  nests this block under ``_detail`` on the merged record.

Consequences baked into this model:

* ``posting_date`` is **required** — it exists only in the detail
  JSON-LD, and roughly 6% of listed jobs point at a page that already
  404s (stale listings still served by the list API; measured over the
  first 100 items, 2026-10-05). Requiring the date lets the parser skip
  exactly those records — honest absence — instead of inserting a row
  whose NOT NULL jobs key would have to be faked from the *deadline*.
* ``location_raw`` prefers the JSON-LD ``addressLocality`` (structured
  address, English for Yerevan) and falls back to the list's Armenian
  display value when the detail payload is present-but-different or the
  job's page is one of the dead ones. Both originals always remain in
  ``raw_payload``.
* ``IndustryId(s)`` are kept in ``raw_payload`` but have no model field:
  ``ref.industries`` is empty for every source so far (Indeed included),
  so mapping them would be a seed project of its own, not a parse.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ASP.NET's MS JSON date: "/Date(1793764070200)/" (epoch millis, UTC).
_MS_JSON_DATE_RE = re.compile(r"^/Date\((-?\d+)\)/$")


def _parse_iso_date(value: object) -> datetime | None:
    """Parse job.am's ISO date string (``"2026-10-05"``) to UTC midnight."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.strptime(value.strip()[:10], "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _parse_ms_json_date(value: object) -> datetime | None:
    """Parse the list payload's ``/Date(1793764070200)/`` deadline."""
    if isinstance(value, str):
        match = _MS_JSON_DATE_RE.match(value.strip())
        if match:
            return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=UTC)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    return None


class RawJobAmJob(BaseModel):
    """A single validated job record as returned by Job.am.

    Attributes:
        source_job_id: Job.am's numeric ``Id``, stringified.
        job_title: Raw ``Title`` (often Armenian — stored as-is, like
            every other source's original-language titles).
        company_name: Raw ``Company`` — 100% populated on the list
            payload (1136/1136, 2026-10-05); the JSON-LD
            ``hiringOrganization.name`` is the fallback.
        company_logo_url: Raw ``Logo`` (a job.am file URL).
        location_raw: See module docstring — JSON-LD ``addressLocality``
            preferred, list ``Location`` as fallback.
        original_url: Canonical public page URL from the list payload's
            ``Url`` (confirmed live, HTTP 200).
        posting_date: Parsed JSON-LD ``datePosted``. **Required**: the
            parser skips a record without it (dead detail page), because
            storage needs a real posting date and job.am's list payload
            has none.
        closing_date: Parsed JSON-LD ``validThrough`` (deadline) with
            the list payload's ``DeadLine`` MS-date as fallback. A
            deadline, not a posting date — kept separate deliberately.
        employment_type_raw: JSON-LD ``employmentType``, multi-valued
            strings included (e.g. "Full Time, Part Time"); the cleaner
            maps a single code out of it.
        description_raw: JSON-LD ``description`` (plain text).
        raw_payload: The complete merged record (list entry + ``_detail``
            JSON-LD), kept for auditability.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    source_job_id: str = Field(alias="Id", min_length=1)
    job_title: str = Field(alias="Title", min_length=1)
    company_name: str = Field(min_length=1)
    company_logo_url: str | None = Field(default=None, alias="Logo")
    location_raw: str | None = None
    original_url: str = Field(alias="Url", min_length=1)
    posting_date: datetime = Field(alias="datePosted")
    closing_date: datetime | None = Field(default=None, alias="validThrough")
    employment_type_raw: str | None = Field(default=None, alias="employmentType")
    description_raw: str | None = Field(default=None, alias="description")
    raw_payload: dict = Field(default_factory=dict, exclude=False)

    @field_validator("source_job_id", mode="before")
    @classmethod
    def _stringify_id(cls, value: object) -> str:
        if value is None:
            raise ValueError("Id must not be null")
        text = str(value).strip()
        if not text:
            raise ValueError("Id must not be empty")
        return text

    @field_validator("posting_date", mode="before")
    @classmethod
    def _parse_posted_at(cls, value: object) -> object:
        """``datePosted`` is ISO (``"2026-10-05"``); unparseable/absent
        fails validation on purpose — that is how dead detail pages get
        skipped rather than stored with a fabricated date."""
        parsed = _parse_iso_date(value)
        if parsed is None:
            raise ValueError(
                f"datePosted missing or unparseable ({value!r}) — no verifiable "
                "posting date (the listing's detail page is likely gone)"
            )
        return parsed

    @field_validator("closing_date", mode="before")
    @classmethod
    def _parse_valid_through(cls, value: object) -> datetime | None:
        """Prefer JSON-LD ``validThrough`` (ISO); fall back to the list
        payload's ``DeadLine`` (``/Date(...)/``); None if neither parses."""
        return _parse_iso_date(value) or _parse_ms_json_date(value)

    @classmethod
    def from_api_entry(cls, entry: dict) -> RawJobAmJob:
        """Build a validated job from the client's merged record.

        The client nests the detail page's JSON-LD under ``_detail``;
        list fields come from the top level. Either side alone is
        enough for the list-carried fields, but ``posting_date`` needs
        ``_detail.datePosted`` (see the module docstring).
        """
        detail = entry.get("_detail")
        if not isinstance(detail, dict):
            detail = {}
        # schema.org allows jobLocation/address to arrive as a list or a
        # non-dict; normalize to the observed dict shape so a payload
        # oddity surfaces as a ValidationError (skipped record), never as
        # an AttributeError escaping the parser's guard.
        job_location = detail.get("jobLocation") or {}
        if isinstance(job_location, list):
            job_location = job_location[0] if job_location else {}
        if not isinstance(job_location, dict):
            job_location = {}
        address = job_location.get("address") or {}
        if not isinstance(address, dict):
            address = {}
        organization = detail.get("hiringOrganization") or {}
        if not isinstance(organization, dict):
            organization = {}

        location = (
            address.get("addressLocality")
            if isinstance(address.get("addressLocality"), str) and address.get("addressLocality")
            else entry.get("Location")
        )

        company = entry.get("Company")
        if not isinstance(company, str) or not company.strip():
            company = organization.get("name")
        if not isinstance(company, str) or not company.strip():
            company = "Anonymous"

        return cls(
            Id=entry.get("Id"),
            Title=entry.get("Title") or "",
            company_name=company.strip(),
            Logo=entry.get("Logo"),
            Url=entry.get("Url") or "",
            location_raw=location,
            datePosted=detail.get("datePosted"),
            validThrough=detail.get("validThrough") or entry.get("DeadLine"),
            employmentType=detail.get("employmentType"),
            description=detail.get("description"),
            raw_payload=entry,
        )
