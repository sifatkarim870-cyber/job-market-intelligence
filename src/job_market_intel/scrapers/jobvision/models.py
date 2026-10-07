"""Typed model for a single raw Jobvision job record.

Mirrors the role ``scrapers/glints/models.py`` plays: the raw,
source-specific shape — API ``data`` dict plus the client's injected
canonical URL — one step before ``cleaning/jobvision_cleaner.py`` maps
it onto the shared ``CleanedJob``.

Field facts confirmed live (2026-10-07) against the public
``JobPost/Detail`` API (25-job sample via r8, three full payloads via
r7/r9):

* **Identity** — ``id`` (int, e.g. ``1550047``) is the job id; there is
  no schema.org ``identifier`` anywhere. The API gives no job URL, so
  the client injects the sitemap's canonical ``/jobs/{id}/{persian-
  slug}`` URL as ``original_url`` (same injection pattern Glints uses).
* **``title``** — Persian, employer-written. ``company.name.titleFa``
  (fallback ``titleEn``) names the employer; ``company.logoUrl`` is a
  stable ``fileapi.jobvision.ir`` image URL (observed on 3/3 payloads,
  absent ⇒ None; "Anonymous" only when the whole company block is
  missing — the Glints stance, since a company-less job is still a
  job).
* **``description``** — full HTML (``<div dir="rtl"><ul>…`` observed);
  the cleaner strips it with ``clean_html_text``.
* **Dates** — ``activationTime.date`` (ISO-8601 ``…Z``) is when the
  *current* activation began and matches the sitemap ``lastmod``
  (observed 2026-10-03T15:06:50Z both places) ⇒ ``posting_date``;
  ``firstActivationTime.date`` (re-activations) and
  ``expireTime.date`` (⇒ ``closing_date``) are carried for audit.
* **Salary** — ``salary`` is either ``null`` (10 of 25 sampled jobs —
  negotiate/unstated ⇒ honest undisclosed) or
  ``{min, max, titleFa: "26 - 30 میلیون تومان", titleEn: "26 - 30
  Million Tomans"}`` with **both bounds in millions of Toman**. The raw
  model keeps those source units (``salary_min_raw``) — scaling to
  whole Toman is a normalization decision and belongs to the cleaner.
* **Employment** — ``workType.titleEn`` (``"Full Time"`` 23/25,
  ``"Full Time Or Part Time"`` 2/25 observed) plus the site's own
  ``isInternship`` boolean, which the cleaner treats as authoritative.
* **Location** — ``location.{city,province,country}`` each
  ``{id, title, titleFa, titleEn}``; the model keeps Persian pieces
  ``[city, province]`` in source order (``country_fa`` rides along as
  the currency anchor — the site is Iran-only) and the cleaner joins.
* **Tag sources** — ``jobCategories`` (occupation paths, present on
  25/25), ``softwareRequirements`` (``{software, skill}`` pairs —
  Word/Excel/سپیدار/تدبیر observed), ``languageRequirements``
  (``{language, skill}`` pairs), company ``industries``, and ``skills``
  (an empty list on 55/55 sampled jobs — still read defensively).
  Everything else on the payload (gender, age caps, military-service
  question, work-days text, benefits, …) is deliberately NOT modeled —
  it stays in ``raw_payload`` only.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, field_validator


def _text(value: object) -> str | None:
    """Trimmed non-empty string, or None — tolerates ``"None"``/blank."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None":
        return None
    return text


def _localized(value: object) -> str | None:
    """``{titleFa, titleEn}`` (or ``{title}``) → the Persian string first."""
    if not isinstance(value, dict):
        return _text(value)
    return _text(value.get("titleFa")) or _text(value.get("title")) or _text(
        value.get("titleEn")
    )


def _iso_date(value: object) -> datetime | None:
    """Parse Jobvision's ISO-8601 timestamps (``…Z`` observed).

    Naive timestamps are assumed UTC. Unparseable values become
    ``None`` — honest absence rather than a crash; the batch validator
    flags rows missing a posting date.
    """
    if value is None or value == "" or value == "None":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _money(value: object) -> int | None:
    """Coerce a salary bound to int in **source units** (millions of Toman).

    Keeps ``0`` (the cleaner applies the ≤0 → unstated rule); anything
    unparseable becomes ``None``.
    """
    if value is None or value == "" or value == "None":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _fa_list(value: object) -> list[str]:
    """``[{titleFa, …}, …]`` → non-empty Persian strings, first-seen order."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _localized(item)
        if text:
            out.append(text)
    return out


class RawJobvisionJob(BaseModel):
    """A single validated Jobvision job record (API ``data`` + URL).

    Attributes:
        source_job_id: The job's ``id``, stringified.
        job_title: ``title`` — employer-written Persian; the
            translation layer makes it English downstream.
        company_name: ``company.name.titleFa`` → ``titleEn`` →
            "Anonymous" when the whole company block is missing.
        company_logo_url: ``company.logoUrl`` (stable fileapi URL).
        description_html: ``description`` — HTML, source language.
        posting_date: ``activationTime.date`` (current activation ⇒
            matches sitemap ``lastmod``).
        closing_date: ``expireTime.date`` (absent ⇒ None).
        work_type_en: ``workType.titleEn`` ("Full Time" observed;
            "Full Time Or Part Time" also seen) — the field the cleaner
            maps onto ``ref.employment_types``.
        is_internship: The site's own flag; the cleaner treats it as
            authoritative over ``work_type_en``.
        salary_min_raw / salary_max_raw: ``salary.min``/``salary.max``
            in **millions of Toman** (source units — the cleaner
            scales); None when ``salary`` is null.
        salary_title_fa: ``salary.titleFa`` ("26 - 30 میلیون تومان") —
            the disclosure/unit evidence the cleaner checks.
        location_parts: ``[city, province]`` Persian pieces, source
            order, missing pieces dropped.
        country_fa: ``location.country.titleFa`` ("ایران" observed on
            25/25) — the currency fallback anchor.
        category_raws / software_names / language_names /
        industry_raws / skills_raws: the five tag sources (see module
            docstring); the cleaner merges them into ``skills``.
        link_out_address: External apply URL when the poster set one
            (null on observed rows — on-platform apply ⇒ the cleaner
            falls back to ``original_url``).
        original_url: Injected by the client from the sitemap.
        raw_payload: The complete API ``data`` dict, for audit.
    """

    source_job_id: str
    job_title: str
    company_name: str
    company_logo_url: str | None = None
    description_html: str | None = None
    posting_date: datetime | None = None
    closing_date: datetime | None = None
    work_type_en: str | None = None
    is_internship: bool = False
    salary_min_raw: int | None = None
    salary_max_raw: int | None = None
    salary_title_fa: str | None = None
    location_parts: list[str] = []
    country_fa: str | None = None
    category_raws: list[str] = []
    software_names: list[str] = []
    language_names: list[str] = []
    industry_raws: list[str] = []
    skills_raws: list[str] = []
    link_out_address: str | None = None
    original_url: str
    raw_payload: dict

    @field_validator("source_job_id", "job_title", mode="after")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("original_url", mode="after")
    @classmethod
    def _url_non_empty(cls, value: str) -> str:
        # Injected by the client from the sitemap; an empty one means
        # the payload lost its canonical URL and the record is
        # unusable (the same stance Jobinja's model takes).
        if not value.strip():
            raise ValueError("original_url must be a non-empty string")
        return value

    @classmethod
    def from_payload(cls, payload: object, *, original_url: str) -> "RawJobvisionJob":
        """Build the model from an API ``data`` dict.

        Raises:
            ValueError: If the payload is not a JSON object (the
                parser turns that into a skip).
        """
        if not isinstance(payload, dict):
            raise ValueError(f"payload must be a JSON object, got {type(payload).__name__}")

        company = payload.get("company")
        company = company if isinstance(company, dict) else {}
        location = payload.get("location")
        location = location if isinstance(location, dict) else {}

        name = company.get("name")
        name = name if isinstance(name, dict) else {}
        company_name = (
            _text(name.get("titleFa"))
            or _text(name.get("titleEn"))
            or _text(name.get("title"))
            or "Anonymous"
        )

        salary = payload.get("salary")
        salary = salary if isinstance(salary, dict) else {}

        activation = payload.get("activationTime")
        activation = activation if isinstance(activation, dict) else {}
        first_activation = payload.get("firstActivationTime")
        first_activation = first_activation if isinstance(first_activation, dict) else {}
        expire = payload.get("expireTime")
        expire = expire if isinstance(expire, dict) else {}

        city = _localized(location.get("city")) if isinstance(location.get("city"), dict) else None
        province = _localized(location.get("province")) if isinstance(location.get("province"), dict) else None
        country = _localized(location.get("country")) if isinstance(location.get("country"), dict) else None

        work_type = payload.get("workType")
        work_type = work_type if isinstance(work_type, dict) else {}

        # softwareRequirements: [{software: {titleFa}, skill: {…}}];
        # languageRequirements: [{language: {titleFa}, skill: {…}}].
        software_names: list[str] = []
        raw_software = payload.get("softwareRequirements")
        if isinstance(raw_software, list):
            for item in raw_software:
                if isinstance(item, dict):
                    text = _localized(item.get("software"))
                    if text:
                        software_names.append(text)
        language_names: list[str] = []
        raw_languages = payload.get("languageRequirements")
        if isinstance(raw_languages, list):
            for item in raw_languages:
                if isinstance(item, dict):
                    text = _localized(item.get("language"))
                    if text:
                        language_names.append(text)

        location_parts = [piece for piece in (city, province) if piece]

        return cls(
            source_job_id=str(payload.get("id") or ""),
            job_title=_text(payload.get("title")) or "",
            company_name=company_name,
            company_logo_url=_text(company.get("logoUrl")),
            description_html=_text(payload.get("description")),
            posting_date=_iso_date(activation.get("date"))
            or _iso_date(first_activation.get("date")),
            closing_date=_iso_date(expire.get("date")),
            work_type_en=_text(work_type.get("titleEn")),
            is_internship=bool(payload.get("isInternship")),
            salary_min_raw=_money(salary.get("min")),
            salary_max_raw=_money(salary.get("max")),
            salary_title_fa=_text(salary.get("titleFa")),
            location_parts=location_parts,
            country_fa=country,
            category_raws=_fa_list(payload.get("jobCategories")),
            software_names=software_names,
            language_names=language_names,
            industry_raws=_fa_list(company.get("industries")),
            skills_raws=_fa_list(payload.get("skills")),
            link_out_address=_text(payload.get("linkOutAddress")),
            original_url=original_url,
            raw_payload=payload,
        )
