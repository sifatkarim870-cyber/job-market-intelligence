"""Typed model for a single raw Glints job record.

Mirrors the role ``scrapers/hrge/models.py`` plays for HR.ge: the raw,
source-specific shape, one step before ``cleaning/glints_cleaner.py``
maps it onto the shared ``CleanedJob``.

Field facts confirmed live (2026-10-07) against job pages served from
the sitemap index (``https://glints.com/sitemap_index.xml``):

* **Full record** — every ``/{cc}/opportunities/jobs/{slug}/{uuid}``
  page embeds ``__NEXT_DATA__.props.pageProps.initialData.data`` with
  ~67 keys: ``id`` (uuid), ``title``, ``descriptionJsonString``
  (Draft.js JSON: ``{"blocks": [{"text": …}], "entityMap": {}}``),
  ``createdAt``/``updatedAt``/``expiryDate``, ``type`` (FULL_TIME /
  PART_TIME / INTERNSHIP / …), ``status`` (OPEN), ``salaries`` (list
  with ``minAmount``/``maxAmount``/``CurrencyCode``/``salaryMode``
  MONTH/YEAR/…/``salaryType`` BASIC — observed IDR 1–2M, SGD 3.4–4.2k,
  VND 25–35M monthly ranges), ``shouldShowSalary``, ``location``
  (``formattedName`` + ``parents`` chain: District → City → Province →
  country), ``hierarchicalJobCategory`` (``name`` e.g. "Store Crew"),
  ``JobSkills`` (``[{"mustHave": …, "skill": {"name": …}}]`` or null),
  ``company`` (``brandName``/``displayName``/``name``, ``industry``
  ``{id, name}`` or null), ``isRemote`` + ``workArrangementOption``
  (ONSITE/HYBRID/REMOTE), ``jobSource`` (EMPLOYER/SOURCED),
  ``externalApplyURL``, and personal-screening junk (``gender``,
  ``minAge``/``maxAge``) that is deliberately NOT modeled — it stays
  in ``raw_payload`` only.
* **Sourced-job fallback** — ``/{cc}/opportunities/s/{slug}/{uuid}``
  pages (the form ``sitemap_sourced_job_*`` entries use) embed their
  record under ``pageProps.sourcedJob`` with only 16 keys: no
  location/category/status/expiry, and salary flattened to
  ``minSalary``/``maxSalary``/``salaryCurrencyCode``. The client first
  rewrites ``/s/`` → ``/jobs/`` (which serves the full record, guarded
  by an ``id == uuid`` check); this model still accepts the flattened
  shape as a last resort so a page-shape change degrades to "fewer
  fields" instead of "no jobs".

``original_url`` is not a Glints field — the client injects it into the
payload (the sitemap's own canonical URL for the job, local-locale
form) so the model can treat it like every other source's URL.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _parse_iso_date(value: object) -> datetime | None:
    """Parse Glints' timestamps: full ISO-8601 (``createdAt``) or date-only (``expiryDate``).

    Naive timestamps are assumed UTC (the site renders them without an
    offset). Unparseable values become ``None`` — honest absence rather
    than a crash; the batch validator flags rows missing a posting date.
    """
    if value is None or value == "" or value == "None":
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


def _text_or_none(value: object) -> str | None:
    """Trimmed non-empty string, or None — tolerates ``"None"``/blank."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None":
        return None
    return text


class RawGlintsJob(BaseModel):
    """A single validated job record as returned by a Glints job page.

    Attributes:
        source_job_id: The job's uuid (``id``), stringified.
        job_title: ``title`` — employer-written, source language (ID/VN)
            or English (SG/EN postings); the translation layer handles
            the non-English ones downstream.
        company_name: ``company.brandName`` falling back to
            ``displayName``/``name``; "Anonymous" when missing.
        country_code: ``CountryCode`` (ID/SG/VN/MY observed) — the
            fallback anchor for currency when a sourced-job payload
            omits the salary list.
        category_raw: ``hierarchicalJobCategory.name`` (e.g.
            "Store Crew").
        industry_raw: ``company.industry.name`` (e.g. "Accounting"),
            null when the company carries no industry.
        contract_type_raw: ``type`` enum — "FULL_TIME" / "PART_TIME" /
            "INTERNSHIP" / … — the field the cleaner maps onto
            ``ref.employment_types``.
        work_arrangement_raw: ``workArrangementOption`` (ONSITE /
            HYBRID / REMOTE); kept for auditability and the
            work-from-home flag.
        location_raw: ``location.formattedName`` plus its ``parents``
            chain, comma-joined nearest-first, e.g. "Penjaringan,
            Jakarta Utara, DKI Jakarta, Indonesia".
        salary_from_raw / salary_to_raw: ``salaries[0]``'s
            ``minAmount``/``maxAmount`` (monthly figures on observed
            rows), or the sourced-job flat ``minSalary``/``maxSalary``.
        salary_currency: ``CurrencyCode`` (IDR/VND/SGD/MYR observed).
        salary_mode: ``salaryMode`` (MONTH observed; YEAR/DAY/HOUR are
            the other Glints modes).
        payment_frequency: ``paymentFrequency`` (null on every observed
            row — the mode carries the period instead).
        should_show_salary: The disclosure flag. Observed pairing:
            disclosed rows have amounts **and** ``shouldShowSalary:
            true``; the cleaner withholds when the flag is explicitly
            false (same rule as HR.ge's ``showSalary``).
        is_work_from_home: ``isRemote`` OR ``workArrangementOption ==
            "REMOTE"``.
        tags: ``JobSkills`` names + category + industry name — the
            cleaner de-duplicates/lowercases them into ``skills``.
        description_raw: ``descriptionJsonString`` — Draft.js JSON
            (the cleaner turns blocks into plain text).
        original_url: The sitemap's canonical local-locale URL for the
            job, injected by the client.
        posting_date: Parsed ``createdAt``.
        closing_date: Parsed ``expiryDate`` (date-only).
        status: ``status`` (OPEN observed; kept for auditability).
        job_source: ``jobSource`` (EMPLOYER / SOURCED).
        external_apply_url: ``externalApplyURL`` — an external ATS
            link when the posting redirects applications off-platform.
        raw_payload: The complete page record, kept for auditability.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    source_job_id: str = Field(alias="id", min_length=1)
    job_title: str = Field(alias="title", min_length=1)
    company_name: str = Field(min_length=1)
    country_code: str | None = Field(default=None, alias="CountryCode")
    category_raw: str | None = None
    industry_raw: str | None = None
    contract_type_raw: str | None = Field(default=None, alias="type")
    work_arrangement_raw: str | None = Field(default=None, alias="workArrangementOption")
    location_raw: str | None = None
    salary_from_raw: int | None = None
    salary_to_raw: int | None = None
    salary_currency: str | None = None
    salary_mode: str | None = None
    payment_frequency: str | None = None
    should_show_salary: bool | None = Field(default=None, alias="shouldShowSalary")
    is_work_from_home: bool = False
    tags: list[str] = Field(default_factory=list)
    description_raw: str | None = Field(default=None, alias="descriptionJsonString")
    original_url: str = Field(min_length=1)
    posting_date: datetime | None = Field(default=None, alias="createdAt")
    closing_date: datetime | None = Field(default=None, alias="expiryDate")
    status: str | None = None
    job_source: str | None = Field(default=None, alias="jobSource")
    external_apply_url: str | None = Field(default=None, alias="externalApplyURL")
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

    @field_validator("posting_date", "closing_date", mode="before")
    @classmethod
    def _iso_to_datetime(cls, value: object) -> datetime | None:
        return _parse_iso_date(value)

    @field_validator("salary_from_raw", "salary_to_raw", mode="before")
    @classmethod
    def _coerce_salary(cls, value: object) -> int | None:
        if value is None or value == "" or value == "None":
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
    def from_page_payload(cls, data: dict, *, original_url: str) -> RawGlintsJob:
        """Build a validated job from a page's embedded record.

        Accepts both observed payload shapes: the full
        ``initialData.data`` record (~67 keys) and the sourced-job
        ``pageProps.sourcedJob`` fallback (16 keys, salary flattened).

        Args:
            data: The record dict extracted from ``__NEXT_DATA__``.
            original_url: The sitemap's canonical URL for this job,
                stored as ``original_url``/``apply_url`` material.

        Raises:
            pydantic.ValidationError: If required identity fields
                (``id``/``title``) are missing — the parser logs and
                skips such records rather than failing the run.
        """
        company = data.get("company") if isinstance(data.get("company"), dict) else {}
        industry = company.get("industry") if isinstance(company.get("industry"), dict) else {}
        category = (
            data.get("hierarchicalJobCategory")
            if isinstance(data.get("hierarchicalJobCategory"), dict)
            else {}
        )

        company_name = (
            _text_or_none(company.get("brandName"))
            or _text_or_none(company.get("displayName"))
            or _text_or_none(company.get("name"))
            or "Anonymous"
        )

        # Location: formattedName + parents chain, nearest first.
        location = data.get("location") if isinstance(data.get("location"), dict) else None
        location_raw = None
        if location:
            parts: list[str] = []
            for candidate in [location.get("formattedName"), location.get("name")]:
                text = _text_or_none(candidate)
                if text and text not in parts:
                    parts.append(text)
                    break
            parents = location.get("parents") if isinstance(location.get("parents"), list) else []
            for parent in parents:
                if isinstance(parent, dict):
                    text = _text_or_none(parent.get("formattedName")) or _text_or_none(
                        parent.get("name")
                    )
                    if text and text not in parts:
                        parts.append(text)
            location_raw = ", ".join(parts) or None

        # Salary: full-record list shape first, sourced flat shape second.
        salary_from = salary_to = None
        salary_currency = salary_mode = payment_frequency = None
        salaries = data.get("salaries")
        if isinstance(salaries, list) and salaries and isinstance(salaries[0], dict):
            first = salaries[0]
            salary_from = first.get("minAmount")
            salary_to = first.get("maxAmount")
            salary_currency = _text_or_none(first.get("CurrencyCode"))
            salary_mode = _text_or_none(first.get("salaryMode"))
            payment_frequency = _text_or_none(first.get("paymentFrequency"))
        else:
            salary_from = data.get("minSalary")
            salary_to = data.get("maxSalary")
            salary_currency = _text_or_none(data.get("salaryCurrencyCode"))
            salary_mode = _text_or_none(data.get("salaryMode"))

        # Tags: Glints' own skill chips + category + industry (the
        # cleaner de-duplicates/lowercases them into ``skills``).
        tags: list[str] = []
        job_skills = data.get("JobSkills")
        if isinstance(job_skills, list):
            for entry in job_skills:
                if isinstance(entry, dict) and isinstance(entry.get("skill"), dict):
                    name = _text_or_none(entry["skill"].get("name"))
                    if name and name not in tags:
                        tags.append(name)
        for extra in (category.get("name"), industry.get("name")):
            text = _text_or_none(extra)
            if text and text not in tags:
                tags.append(text)

        arrangement = _text_or_none(data.get("workArrangementOption"))
        is_remote = bool(data.get("isRemote")) or arrangement == "REMOTE"

        return cls(
            id=data.get("id", ""),
            title=data.get("title") or "",
            company_name=company_name,
            CountryCode=_text_or_none(data.get("CountryCode")),
            category_raw=_text_or_none(category.get("name")),
            industry_raw=_text_or_none(industry.get("name")),
            type=_text_or_none(data.get("type")),
            workArrangementOption=arrangement,
            location_raw=location_raw,
            salary_from_raw=salary_from,
            salary_to_raw=salary_to,
            salary_currency=salary_currency,
            salary_mode=salary_mode,
            payment_frequency=payment_frequency,
            shouldShowSalary=data.get("shouldShowSalary"),
            is_work_from_home=is_remote,
            tags=tags,
            descriptionJsonString=_text_or_none(data.get("descriptionJsonString")),
            original_url=original_url,
            createdAt=data.get("createdAt"),
            expiryDate=data.get("expiryDate"),
            status=_text_or_none(data.get("status")),
            jobSource=_text_or_none(data.get("jobSource")),
            externalApplyURL=_text_or_none(data.get("externalApplyURL")),
            raw_payload=data,
        )
