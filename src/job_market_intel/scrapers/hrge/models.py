"""Typed model for a single raw HR.ge job record.

Mirrors the role ``scrapers/myjob/models.py`` plays for MyJob.mu: the
raw, source-specific shape, one step before ``cleaning/hrge_cleaner.py``
maps it onto the shared ``CleanedJob``.

Field facts confirmed live (2026-10-06/07) against
``api.p.hr.ge/public-portal/tenant/1/api/v3/``:

* **List** — ``POST announcement-search`` (offset paging via
  ``start``/``limit`` ≤ 100) returns items with ``announcementId``,
  ``customerId``, ``customerName``, ``title``, ``publishDate``/
  ``deadlineDate`` (ISO-8601), ``locations`` (city names, English under
  ``Accept-Language: en``), ``isWorkFromHome``, ``logoFilename`` and a
  ``status``/``publishStatus`` pair — but no description or taxonomy.
* **Detail** — ``GET announcement/{id}`` returns a 150-field superset:
  HTML ``description``, ``addresses``, ``salaryFrom``/``salaryTo`` with
  ``showSalary``/``hideSalary`` flags, and ``announcementRequirements``
  (``specializationList``/``industryList``/``seniorityLevels`` name
  trees plus the enums ``workScheduleName`` "Full-time",
  ``employmentTypeName`` "Fixed-term contract"/"Open-ended contract",
  ``employmentFormTypeName`` "On site") — all English under
  ``Accept-Language: en``. The client merges detail over list (detail
  wins on non-null keys) before parsing.

Georgian-only postings return their description behind the English
notice "This announcement is available only in Georgian Language...",
which the cleaner strips as noise; the remaining Georgian body is
handled by the translation layer.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _parse_iso_date(value: object) -> datetime | None:
    """Parse one of HR.ge's ISO-8601 timestamps ("2026-10-06T17:17:03.857").

    Naive timestamps are assumed UTC (the API serves them without an
    offset). Unparseable values become ``None`` — honest absence rather
    than a crash; the batch validator flags rows missing a posting date.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _first_name(entries: object) -> str | None:
    """First ``name`` from a taxonomy list like ``specializationList``."""
    if isinstance(entries, list) and entries:
        first = entries[0]
        if isinstance(first, dict):
            name = first.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return None


class RawHRGeJob(BaseModel):
    """A single validated job record as returned by HR.ge's API.

    Attributes:
        source_job_id: ``announcementId``, stringified.
        job_title: ``title`` — English under ``Accept-Language: en``
            when the site/employer provides one, Georgian otherwise.
        company_name: ``customerName`` — "Anonymous" when missing or
            when ``isAnonymous`` is set (some employers hide their name).
        company_logo_url: ``logoUrl`` (detail) or ``logoFilename`` (list).
        category_raw: First ``specializationList`` name (e.g.
            "Human resources"), English under the en header.
        industry_raw: First ``industryList`` name (e.g. "Retail").
        seniority_raw: First ``seniorityLevels`` entry (e.g. "Mid-Level").
        contract_type_raw: ``employmentTypeName`` ("Fixed-term contract"
            / "Open-ended contract").
        work_schedule_raw: ``workScheduleName`` ("Full-time" /
            "Part-time") — the field the cleaner prefers when mapping
            onto ``ref.employment_types``.
        work_form_raw: ``employmentFormTypeName`` ("On site" / …);
            kept for auditability (``CleanedJob`` has no field for it).
        location_raw: ``addresses`` (detail) falling back to ``locations``
            (list), comma-joined — e.g. "Tbilisi" or "Tbilisi, Batumi".
        salary_from_raw / salary_to_raw: ``salaryFrom``/``salaryTo``
            integers (GEL/month on this board); may be half-open.
        show_salary / hide_salary: The disclosure flags. Observed
            pairing: disclosed rows have amounts **and** ``showSalary:
            true``; withheld rows carry ``showSalary: false``. The
            cleaner treats any explicit withhold flag as not disclosed.
        is_work_from_home: ``isWorkFromHome`` flag from the list payload.
        tags: Specialization + industry names (English under the en
            header) — the cleaner de-duplicates/lowercases them into
            ``skills``.
        description_raw: Detail-only HTML ``description``.
        original_url: Canonical public page URL,
            ``https://www.hr.ge/announcement/{id}`` (confirmed live —
            the slug-less form SSRs the full announcement).
        posting_date: Parsed ``publishDate``.
        closing_date: Parsed ``deadlineDate``.
        raw_payload: The complete merged record, kept for auditability.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    source_job_id: str = Field(alias="announcementId", min_length=1)
    job_title: str = Field(alias="title", min_length=1)
    company_name: str = Field(min_length=1)
    company_logo_url: str | None = None
    category_raw: str | None = None
    industry_raw: str | None = None
    seniority_raw: str | None = None
    contract_type_raw: str | None = None
    work_schedule_raw: str | None = None
    work_form_raw: str | None = None
    location_raw: str | None = None
    salary_from_raw: int | None = Field(default=None, alias="salaryFrom")
    salary_to_raw: int | None = Field(default=None, alias="salaryTo")
    show_salary: bool | None = Field(default=None, alias="showSalary")
    hide_salary: bool | None = Field(default=None, alias="hideSalary")
    is_work_from_home: bool = Field(default=False, alias="isWorkFromHome")
    tags: list[str] = Field(default_factory=list)
    description_raw: str | None = Field(default=None, alias="description")
    original_url: str = Field(min_length=1)
    posting_date: datetime | None = Field(default=None, alias="publishDate")
    closing_date: datetime | None = Field(default=None, alias="deadlineDate")
    raw_payload: dict = Field(default_factory=dict, exclude=False)

    @field_validator("source_job_id", mode="before")
    @classmethod
    def _stringify_id(cls, value: object) -> str:
        if value is None:
            raise ValueError("announcementId must not be null")
        text = str(value).strip()
        if not text:
            raise ValueError("announcementId must not be empty")
        return text

    @field_validator("posting_date", "closing_date", mode="before")
    @classmethod
    def _iso_to_datetime(cls, value: object) -> datetime | None:
        return _parse_iso_date(value)

    @field_validator("salary_from_raw", "salary_to_raw", mode="before")
    @classmethod
    def _coerce_salary(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: object) -> list[str]:
        if isinstance(value, list):
            return [t.strip() for t in value if isinstance(t, str) and t.strip()]
        return []

    @classmethod
    def from_api_entry(cls, entry: dict) -> RawHRGeJob:
        """Build a validated job from a client-merged list+detail record.

        ``entry`` is the list item with the detail payload merged over it
        (detail wins on non-null keys), so both description/taxonomy
        (detail-only) and ``locations``/``isWorkFromHome`` (list-only)
        are available.
        """
        announcement_id = entry.get("announcementId", "")
        requirements = entry.get("announcementRequirements") or {}
        if not isinstance(requirements, dict):
            requirements = {}

        customer_name = entry.get("customerName")
        if (
            not isinstance(customer_name, str)
            or not customer_name.strip()
            or entry.get("isAnonymous") is True
        ):
            customer_name = "Anonymous"

        addresses = entry.get("addresses") or entry.get("locations") or []
        if isinstance(addresses, list):
            location = ", ".join(
                a.strip() for a in addresses if isinstance(a, str) and a.strip()
            ) or None
        elif isinstance(addresses, str) and addresses.strip():
            location = addresses.strip()
        else:
            location = None

        tags: list[str] = []
        for taxonomy_list in (
            requirements.get("specializationList"),
            requirements.get("industryList"),
        ):
            if isinstance(taxonomy_list, list):
                for item in taxonomy_list:
                    if isinstance(item, dict):
                        name = item.get("name")
                        if isinstance(name, str) and name.strip() and name.strip() not in tags:
                            tags.append(name.strip())

        logo_url = entry.get("logoUrl") or entry.get("logoFilename")
        announcement_id_text = str(announcement_id).strip()
        original_url = f"https://www.hr.ge/announcement/{announcement_id_text}"

        return cls(
            announcementId=announcement_id,
            title=entry.get("title") or "",
            company_name=customer_name.strip(),
            company_logo_url=logo_url if isinstance(logo_url, str) and logo_url.strip() else None,
            category_raw=_first_name(requirements.get("specializationList")),
            industry_raw=_first_name(requirements.get("industryList")),
            seniority_raw=(
                requirements.get("seniorityLevels")[0]
                if isinstance(requirements.get("seniorityLevels"), list)
                and requirements.get("seniorityLevels")
                and isinstance(requirements.get("seniorityLevels")[0], str)
                else None
            ),
            contract_type_raw=(
                requirements.get("employmentTypeName")
                if isinstance(requirements.get("employmentTypeName"), str)
                else None
            ),
            work_schedule_raw=(
                requirements.get("workScheduleName")
                if isinstance(requirements.get("workScheduleName"), str)
                else None
            ),
            work_form_raw=entry.get("employmentFormTypeName")
            if isinstance(entry.get("employmentFormTypeName"), str)
            else None,
            location_raw=location,
            salaryFrom=entry.get("salaryFrom"),
            salaryTo=entry.get("salaryTo"),
            showSalary=entry.get("showSalary"),
            hideSalary=entry.get("hideSalary"),
            isWorkFromHome=bool(entry.get("isWorkFromHome", False)),
            tags=tags,
            description=entry.get("description"),
            original_url=original_url,
            publishDate=entry.get("publishDate"),
            deadlineDate=entry.get("deadlineDate"),
            raw_payload=entry,
        )
