"""Typed model for a single raw MyJob.mu job record.

Mirrors the role ``scrapers/emploitic/models.py`` plays for Emploitic:
the raw, source-specific shape, one step before
``cleaning/myjob_cleaner.py`` maps it onto the shared ``CleanedJob``.

Field facts confirmed live (2026-10-05) against
``app.myjob.mu/api/job-board/jobs`` (list) and ``/jobs/{id}`` (detail):

* List items carry ``id`` (int), ``title``, ``slug``, ``location``,
  ``jobType`` ("Full-time", "Part-time", "Fixed-term contract (CDD)",
  "Temporary", "Internship", "Freelance"), ``salaryRange`` (e.g.
  ``"31,000 – 40,000"`` with an en-dash), ``showSalary`` (bool — when
  false the board displays "Salary not disclosed" even though a range is
  present in the payload), ``category {name, slug}``, ``postedAt``
  ("Posted Oct 4, 2026"), ``closingAt`` ("Closing 03/11/2026", DD/MM/YYYY),
  ``company {id, name, slug, industry?, logo?}`` and
  ``tags [{label}]``.
* The detail endpoint repeats all of the above and adds
  ``workArrangement`` (observed: "Remote") and ``description`` (HTML) —
  the only source of description text, so the client fetches it per job
  when ``MYJOB_FETCH_DETAILS`` is on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _strip_prefix(value: object, prefix: str) -> str | None:
    """Remove a display prefix like "Posted " / "Closing " from a value."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.lower().startswith(prefix.lower()):
        text = text[len(prefix):].strip()
    return text or None


def _parse_listed_date(value: object, prefix: str, fmt: str) -> datetime | None:
    """Parse one of MyJob.mu's display dates ("Posted Oct 4, 2026")."""
    text = _strip_prefix(value, prefix)
    if text is None:
        return None
    try:
        parsed = datetime.strptime(text, fmt)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC)


class RawMyJobJob(BaseModel):
    """A single validated job record as returned by MyJob.mu's API.

    Attributes:
        source_job_id: MyJob.mu's numeric ``id``, stringified.
        job_title: Raw ``title``.
        slug: URL slug; builds ``original_url``.
        company_name: Raw ``company.name`` — falls back to "Anonymous"
            when no name is present.
        company_industry_raw: ``company.industry`` — raw hint, resolved
            to a canonical industry by a later normalization step.
        company_logo_url: ``company.logo`` (an app.myjob.mu file URL).
        category_raw: ``category.name`` (e.g. "Administrative / Clerical").
        contract_type_raw: ``jobType`` (e.g. "Fixed-term contract (CDD)").
        work_mode_raw: Detail-only ``workArrangement`` (e.g. "Remote").
        location_raw: ``location`` (e.g. "Mauritius", "Moka").
        salary_range_raw: ``salaryRange`` string (e.g. "31,000 – 40,000").
        show_salary: ``showSalary`` — the board only displays the salary
            when true; a payload range with ``showSalary: false`` is a
            value the site deliberately withholds, so the cleaner treats
            it as not disclosed.
        tags: Labels from ``tags[].label``, defaulting to empty.
        description_raw: Detail-only HTML ``description``.
        original_url: Canonical public page URL,
            ``https://www.myjob.mu/jobs/{slug}`` (confirmed live).
        posting_date: Parsed ``postedAt`` ("Posted Oct 4, 2026").
        closing_date: Parsed ``closingAt`` ("Closing 03/11/2026",
            DD/MM/YYYY).
        raw_payload: The complete original record, kept for auditability.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    source_job_id: str = Field(alias="id", min_length=1)
    job_title: str = Field(alias="title", min_length=1)
    slug: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    company_industry_raw: str | None = None
    company_logo_url: str | None = None
    category_raw: str | None = None
    contract_type_raw: str | None = Field(default=None, alias="jobType")
    work_mode_raw: str | None = Field(default=None, alias="workArrangement")
    location_raw: str | None = None
    salary_range_raw: str | None = Field(default=None, alias="salaryRange")
    show_salary: bool = Field(default=False, alias="showSalary")
    tags: list[str] = Field(default_factory=list)
    description_raw: str | None = Field(default=None, alias="description")
    original_url: str = Field(min_length=1)
    posting_date: datetime | None = Field(default=None, alias="postedAt")
    closing_date: datetime | None = Field(default=None, alias="closingAt")
    raw_payload: dict = Field(default_factory=dict, exclude=False)

    @field_validator("source_job_id", mode="before")
    @classmethod
    def _stringify_id(cls, value: object) -> str:
        if value is None:
            raise ValueError("id must not be null")
        text = str(value).strip()
        if not text:
            raise ValueError("id must not be empty")
        return text

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: object) -> list[str]:
        """``tags`` is a list of ``{label}`` dicts; flatten to strings."""
        if value is None:
            return []
        if isinstance(value, list):
            labels: list[str] = []
            for entry in value:
                if isinstance(entry, dict):
                    label = entry.get("label")
                    if isinstance(label, str) and label.strip():
                        labels.append(label.strip())
                elif isinstance(entry, str) and entry.strip():
                    labels.append(entry.strip())
            return labels
        return []

    @field_validator("posting_date", mode="before")
    @classmethod
    def _parse_posted_at(cls, value: object) -> datetime | None:
        """``postedAt`` is human-readable: 'Posted Oct 4, 2026'."""
        return _parse_listed_date(value, "Posted", "%b %d, %Y")

    @field_validator("closing_date", mode="before")
    @classmethod
    def _parse_closing_at(cls, value: object) -> datetime | None:
        """``closingAt`` is DD/MM/YYYY: 'Closing 03/11/2026'."""
        return _parse_listed_date(value, "Closing", "%d/%m/%Y")

    @classmethod
    def from_api_entry(cls, entry: dict, *, detail: dict | None = None) -> RawMyJobJob:
        """Build a validated job from a list entry, optionally merged with
        its detail payload.

        The detail response is a superset of the list response (same
        shape, plus ``description``/``workArrangement``), so it is merged
        over the list entry first; either side alone is enough to build
        a record.
        """
        merged: dict = dict(entry)
        if detail:
            merged.update({k: v for k, v in detail.items() if v is not None})

        company = merged.get("company") or {}
        company_name = company.get("name") or ""
        if not isinstance(company_name, str) or not company_name.strip():
            company_name = "Anonymous"
        category = merged.get("category") or {}
        slug = merged.get("slug") or ""
        original_url = (
            f"https://www.myjob.mu/jobs/{slug}" if isinstance(slug, str) and slug.strip() else ""
        )
        return cls(
            id=merged.get("id", ""),
            title=merged.get("title", "") or "",
            slug=slug if isinstance(slug, str) else "",
            company_name=company_name.strip(),
            company_industry_raw=company.get("industry")
            if isinstance(company.get("industry"), str)
            else None,
            company_logo_url=company.get("logo")
            if isinstance(company.get("logo"), str)
            else None,
            category_raw=category.get("name") if isinstance(category.get("name"), str) else None,
            jobType=merged.get("jobType"),
            workArrangement=merged.get("workArrangement"),
            location_raw=merged.get("location"),
            salaryRange=merged.get("salaryRange"),
            showSalary=bool(merged.get("showSalary", False)),
            tags=merged.get("tags") or [],
            description=merged.get("description"),
            original_url=original_url,
            postedAt=merged.get("postedAt"),
            closingAt=merged.get("closingAt"),
            raw_payload=merged,
        )
