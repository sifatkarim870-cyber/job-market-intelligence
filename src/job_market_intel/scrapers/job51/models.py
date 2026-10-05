"""Typed model for a single raw 51job job record.

Mirrors the role ``scrapers/jobam/models.py`` plays for Job.am: the raw,
source-specific shape, one step before ``cleaning/job51_cleaner.py`` maps
it onto the shared ``CleanedJob``.

Where each field comes from (confirmed live, 2026-10-05)
--------------------------------------------------------
51job's PC web UI reads one undocumented JSON endpoint:

``GET https://cupid.51job.com/pc/open/noauth/search-h5?pageNum=1&pageSize=100``

with no auth, no cookies, and no signing (see ``client.py``'s module
docstring for how it was found and what was deliberately *not* needed).
Each ``resultbody.job.items[]`` entry is a complete job — this is the
key difference from Job.am, whose list payload lacked the interesting
fields:

* **Identity**: ``jobId`` (numeric string), ``jobName``, ``companyName``
  (display name; ``fullCompanyName`` is the legal name and differs on
  ~87% of items), ``companyLogo``.
* **Location**: ``jobAreaString`` — the board's display value, usually
  ``"城市·区"`` (e.g. ``"佛山·顺德区"``; a bare city like ``"东莞"``
  also occurs; 299/300 populated). Optional here (1/300 empty) — an
  empty location falls to the unmatched-location fallback downstream,
  exactly like every other source's unresolvable text.
* **URL**: ``jobHref`` — canonical page on ``msearch.51job.com`` plus a
  tracking query string (``?rc=…&jobtype=…&req=…``), stripped to the
  canonical form by the ``original_url`` validator.
* **Posting date**: ``issueDateString`` — always observed as
  ``"2026-10-05 16:52:18"`` (300/300, full timestamp). **Required**:
  the parser skips a record without it, because storage needs a real
  posting date (same gate Job.am uses for its dead listings).
* **Salary**: both ``jobSalaryMin``/``jobSalaryMax`` (numeric *strings*
  already normalized to yuan, e.g. ``"12000"`` for the display string
  ``"1.2-1.8万"``) and ``provideSalaryString`` (the human display form,
  which also carries the pay-cadence hints ``千``/``万``/``·13薪`` and,
  in theory, daily/hourly forms like ``元/天``). 300/300 items carried
  all three during scoping — but salary stays optional in the model:
  absence is legitimate (undisclosed pay) and the cleaner records it
  honestly via ``salary_disclosed``.
* **Employment type**: ``termStr`` — observed ``"全职"`` (full-time,
  299/300) and ``"兼职"`` (part-time); the cleaner maps to reference
  codes.
* **Description**: ``jobDescribe`` — full plain text in the list
  payload (34–3,455 chars observed; no detail-page fetch needed).
  ``workYearString``/``degreeString``/``jobTags``/``industryType*Str``
  stay in ``raw_payload`` only: experience/degree/benefit tags are not
  skills, and ``ref.industries`` is empty for every source so far.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _parse_posted_at(value: object) -> datetime | None:
    """Parse 51job's ``issueDateString`` (always a full timestamp during
    scoping; date-only accepted defensively). ``None`` if unparsable."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
    return None


def _parse_salary_bound(value: object) -> int | None:
    """``jobSalaryMin``/``jobSalaryMax`` arrive as numeric strings
    (``"12000"``); ``""``/``"0"``/``None`` mean undisclosed → ``None``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        return int(number) if number > 0 else None
    return None


class RawJob51Job(BaseModel):
    """A single validated job record as returned by 51job.

    Attributes:
        source_job_id: 51job's ``jobId``, stringified.
        job_title: Raw ``jobName`` (Chinese — stored as-is, like every
            other source's original-language titles).
        company_name: ``companyName``, with ``fullCompanyName`` and a
            sentinel as fallbacks (display name is populated 300/300).
        company_logo_url: Raw ``companyLogo`` (a 51job CDN URL).
        location_raw: See module docstring — ``jobAreaString``.
        original_url: ``jobHref`` stripped to its canonical form.
        posting_date: Parsed ``issueDateString``. **Required**: the
            parser skips a record without it (nothing fabricated).
        closing_date: Always ``None`` — 51job's list payload carries no
            deadline/expiry field (300/300 checked); kept for parity
            with the shared ``CleanedJob`` shape, honest absence.
        employment_type_raw: ``termStr`` as-is (e.g. ``"全职"``); the
            cleaner maps one reference code out of it.
        description_raw: ``jobDescribe`` (full plain text).
        salary_min / salary_max: Parsed ``jobSalaryMin``/``jobSalaryMax``
            (yuan, monthly per the display string's cadence).
        salary_text: ``provideSalaryString`` — kept because it is the
            only place a non-monthly cadence (``元/天``) would show.
        raw_payload: The complete API item, kept for auditability.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    source_job_id: str = Field(alias="jobId", min_length=1)
    job_title: str = Field(alias="jobName", min_length=1)
    company_name: str = Field(min_length=1)
    company_logo_url: str | None = Field(default=None, alias="companyLogo")
    location_raw: str | None = Field(default=None, alias="jobAreaString")
    original_url: str = Field(alias="jobHref", min_length=1)
    posting_date: datetime = Field(alias="issueDateString")
    closing_date: datetime | None = None
    employment_type_raw: str | None = Field(default=None, alias="termStr")
    description_raw: str | None = Field(default=None, alias="jobDescribe")
    salary_min: int | None = Field(default=None, alias="jobSalaryMin")
    salary_max: int | None = Field(default=None, alias="jobSalaryMax")
    salary_text: str | None = Field(default=None, alias="provideSalaryString")
    raw_payload: dict = Field(default_factory=dict, exclude=False)

    @field_validator("source_job_id", mode="before")
    @classmethod
    def _stringify_id(cls, value: object) -> str:
        if value is None:
            raise ValueError("jobId must not be null")
        text = str(value).strip()
        if not text:
            raise ValueError("jobId must not be empty")
        return text

    @field_validator("job_title", mode="before")
    @classmethod
    def _require_title(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("jobName missing or empty")
        return value

    @field_validator("posting_date", mode="before")
    @classmethod
    def _parse_issue_date(cls, value: object) -> object:
        """``issueDateString`` must parse; unparseable/absent fails
        validation on purpose — that is how a record without a verifiable
        posting date gets skipped rather than stored with a fabricated
        date (same gate Job.am applies to dead detail pages)."""
        parsed = _parse_posted_at(value)
        if parsed is None:
            raise ValueError(
                f"issueDateString missing or unparseable ({value!r}) — no "
                "verifiable posting date"
            )
        return parsed

    @field_validator("original_url", mode="before")
    @classmethod
    def _strip_tracking_query(cls, value: object) -> object:
        """``jobHref`` ships with ``?rc=…&jobtype=…&req=…`` tracking;
        the canonical page URL (what the board itself shows as the
        job's address) has no query string."""
        if isinstance(value, str) and value.strip():
            return value.strip().split("?", 1)[0]
        return value

    @field_validator("company_name", mode="before")
    @classmethod
    def _company_or_fallback(cls, value: object) -> object:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return value

    @field_validator("salary_min", "salary_max", mode="before")
    @classmethod
    def _parse_salary(cls, value: object) -> int | None:
        return _parse_salary_bound(value)

    @classmethod
    def from_api_entry(cls, entry: dict) -> RawJob51Job:
        """Build a validated job from one raw ``items[]`` dict.

        Fallbacks that cannot be expressed as plain aliases: company
        (``companyName`` → ``fullCompanyName`` → sentinel) and location
        (``jobAreaString`` may legitimately be ``""`` → ``None``).
        Anything structurally wrong (missing ``jobId``/``jobName``/
        ``jobHref``/``issueDateString``) raises ``ValidationError``, which
        ``parser.py`` counts as a skip — never a failed run.
        """
        company = entry.get("companyName")
        if not isinstance(company, str) or not company.strip():
            company = entry.get("fullCompanyName")
        if not isinstance(company, str) or not company.strip():
            company = "Anonymous"

        location = entry.get("jobAreaString")
        if isinstance(location, str) and not location.strip():
            location = None

        return cls(
            jobId=entry.get("jobId"),
            jobName=entry.get("jobName") or "",
            company_name=company.strip(),
            companyLogo=entry.get("companyLogo"),
            jobAreaString=location,
            jobHref=entry.get("jobHref") or "",
            issueDateString=entry.get("issueDateString"),
            termStr=entry.get("termStr"),
            jobDescribe=entry.get("jobDescribe"),
            jobSalaryMin=entry.get("jobSalaryMin"),
            jobSalaryMax=entry.get("jobSalaryMax"),
            provideSalaryString=entry.get("provideSalaryString"),
            raw_payload=entry,
        )
