"""Typed model for a single raw Zangia.mn job record.

Mirrors the role ``scrapers/timesjobs_in/models.py`` plays: the raw,
source-specific shape -- one merged listing row plus its detail record --
one step before ``cleaning/zangia_mn_cleaner.py`` maps it onto the shared
``CleanedJob``.

Field facts confirmed live (2026-11-21; the worked example in
``tests/unit/scrapers/test_zangia_mn.py`` is listing/detail code
``4yr4tnp5cm``):

* **Identity** -- ``code`` is the posting's URL slug (its public page is
  ``https://zangia.mn/job/<code>``) and is the stable ``source_job_id``;
  ``id`` is the numeric primary key and is kept only in ``raw_payload``.
  The listing and detail agree on ``code``.
* **Titles/company** -- ``title`` on both records; ``company.name``
  (detail) -> ``company.name`` (listing). Both agree on the sample.
* **Description** -- the detail carries three HTML blobs: ``description``,
  ``requirements`` and ``additional`` (benefits/notes). All are job
  content with no separate ``CleanedJob`` slot, so the model keeps them
  separately and the cleaner folds them into one cleaned description.
* **Skills** -- an array of objects; the model reads ``name_en`` and falls
  back to ``name_mn`` (the board is bilingual and English names are
  almost always present).
* **Salary** -- ``salary`` is an object ``{id, phrase, min, max}`` in
  whole Mongolian tugrik (MNT), quoted monthly by the board's own
  convention; it was populated on every sampled row. The model keeps the
  numeric bounds and the cleaner applies the zero/hide/reversed rules.
* **Dates** -- the only timestamp is the unix-seconds ``sortTime`` (the
  listing) / ``time`` (the detail), both the same value and the posting
  time (``1795048621`` -> ``2026-11-19T01:15:02Z``); ``isFeatured`` is a
  *featured-until* timestamp, not a posting date, and is not used.
* **Employment** -- the detail's ``timetype`` object carries
  ``{id, name_mn, name_en}`` with ``name_en`` observed as ``"Full-time"``
  or ``"Shift"``; the listing's ``timetype`` is the bare id. The model
  keeps the detail's ``name_en`` so the cleaner can map it onto
  ``ref.employment_types``.
* **Location** -- ``location`` is a district label (e.g. ``"Баянзүрх
  дүүрэг"``) on both records and ``address`` is the street line (detail
  only). The model uses ``location`` as the raw location text and keeps
  ``address`` in ``raw_payload``.
* **No logo URL** -- ``company.logo`` is an opaque code with no
  resolvable CDN URL (every guess 404s), so ``company_logo_url`` is left
  None rather than storing a dead link.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, field_validator


def _text(value: object) -> str | None:
    """Trimmed non-empty string, or None -- tolerates ``"None"``/blank."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None":
        return None
    return text


def _int(value: object) -> int | None:
    """Coerce to int, or None when unparseable/absent (keeps ``0``)."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _epoch(value: object) -> datetime | None:
    """A unix-seconds timestamp -> an aware UTC datetime, or None.

    Zangia's only timestamp field is epoch seconds (``sortTime``/``time``).
    Zero/absent/unparseable values become ``None`` -- honest absence
    rather than a 1970 date.
    """
    seconds = _int(value)
    if seconds is None or seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _skill_names(value: object) -> list[str]:
    """A JSON array of skill objects -> ``name_en`` (else ``name_mn``) labels."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            text = _text(item)
            if text:
                out.append(text)
            continue
        name = _text(item.get("name_en")) or _text(item.get("name_mn"))
        if name:
            out.append(name)
    return out


def _salary_dict(value: object) -> dict:
    """The ``salary`` object from whichever record carries one."""
    return value if isinstance(value, dict) else {}


class RawZangiaJob(BaseModel):
    """A single validated Zangia job record (merged listing + detail).

    Attributes:
        source_job_id: The posting's ``code`` (URL slug), stringified.
        job_title: ``title`` (the board publishes Mongolian, sometimes
            English; no language judgment is made here).
        company_name: ``company.name`` (detail) -> ``company.name``
            (listing).
        company_logo_url: Always None -- the logo code has no resolvable
            URL (see module docstring).
        description_html: HTML ``description`` (detail).
        requirements_html: HTML ``requirements`` (detail).
        additional_html: HTML ``additional`` -- benefits/notes (detail).
        skills_raw: Skill labels from ``skills`` (``name_en`` preferred).
        location_text: ``location`` (detail) -> ``location`` (listing).
        posting_date: The unix-seconds ``time`` (detail) -> ``sortTime``
            (listing), as aware UTC.
        closing_date: Never populated by this board; kept for symmetry.
        employment_type_raw: ``timetype.name_en`` (detail) -- observed
            "Full-time" / "Shift"; the cleaner maps it.
        salary_min_raw / salary_max_raw: ``salary.min``/``salary.max`` in
            whole MNT (the cleaner applies the zero/reversed rules).
        original_url: ``https://zangia.mn/job/<code>``.
        raw_payload: ``{"listing": ..., "detail": ...}`` for audit.
    """

    source_job_id: str
    job_title: str
    company_name: str
    company_logo_url: str | None = None
    description_html: str | None = None
    requirements_html: str | None = None
    additional_html: str | None = None
    skills_raw: list[str] = []
    location_text: str | None = None
    posting_date: datetime | None = None
    closing_date: datetime | None = None
    employment_type_raw: str | None = None
    salary_min_raw: int | None = None
    salary_max_raw: int | None = None
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
        if not value.strip():
            raise ValueError("original_url must be a non-empty string")
        return value

    @classmethod
    def from_payload(
        cls,
        listing: object,
        detail: object,
        *,
        original_url: str,
    ) -> RawZangiaJob:
        """Build the model from one listing row plus its detail record.

        Args:
            listing: The listing row dict (required -- it carries the
                ``code`` used for the detail fetch and the public URL).
            detail: The detail dict, or None when the detail GET failed
                (the listing-only fields still make a usable record).
            original_url: The public ``https://zangia.mn/job/<code>`` URL.

        Raises:
            ValueError: If ``listing`` is not a JSON object (the parser
                turns that into a skip).
        """
        if not isinstance(listing, dict):
            raise ValueError(f"listing must be a JSON object, got {type(listing).__name__}")
        detail_dict = detail if isinstance(detail, dict) else {}

        listing_company = listing.get("company")
        detail_company = detail_dict.get("company")
        listing_company = listing_company if isinstance(listing_company, dict) else {}
        detail_company = detail_company if isinstance(detail_company, dict) else {}

        timetype = detail_dict.get("timetype")
        timetype_name = _text(timetype.get("name_en")) if isinstance(timetype, dict) else None

        salary = _salary_dict(detail_dict.get("salary")) or _salary_dict(listing.get("salary"))

        return cls(
            source_job_id=str(listing.get("code") or detail_dict.get("code") or ""),
            job_title=_text(detail_dict.get("title")) or _text(listing.get("title")) or "",
            company_name=_text(detail_company.get("name"))
            or _text(listing_company.get("name"))
            or "",
            company_logo_url=None,
            description_html=_text(detail_dict.get("description")),
            requirements_html=_text(detail_dict.get("requirements")),
            additional_html=_text(detail_dict.get("additional")),
            skills_raw=_skill_names(detail_dict.get("skills"))
            or _skill_names(listing.get("skills")),
            location_text=_text(detail_dict.get("location")) or _text(listing.get("location")),
            posting_date=_epoch(detail_dict.get("time")) or _epoch(listing.get("sortTime")),
            closing_date=None,
            employment_type_raw=timetype_name,
            salary_min_raw=_int(salary.get("min")),
            salary_max_raw=_int(salary.get("max")),
            original_url=original_url,
            raw_payload={"listing": listing, "detail": detail_dict},
        )
