"""Typed model for a single raw ANPE Mali job record.

The site is a WordPress install running WP Job Manager, so one REST
``job_listing`` object is the whole record -- there is no separate detail
call to merge. The model mirrors the raw, source-specific shape every
other scraper produces, one step before
``cleaning/anpe_mali_cleaner.py`` maps it onto the shared ``CleanedJob``.

Field facts confirmed live (2026-11-21; listing ``2188`` -- "CHARGE(E) DE
PROJET EN GENIE CIVIL / HYDRAULIQUE" -- is the worked example in
``tests/unit/scrapers/test_anpe_mali.py``):

* **Identity** -- ``id`` is the WordPress post id and the stable
  ``source_job_id``; ``link`` is the public page URL (``/poste/<slug>/``).
* **Titles** -- ``title.rendered`` is HTML-escaped text; unescaped once
  here, and NFKC-normalized (a few titles carry stray soft-hyphen and
  Unicode spaces).
* **Employer** -- unlike ANPE Burkina Faso, this board DOES carry the
  employer: ``meta._company_name`` is the hiring organisation, and the
  optional logo is the embedded ``wp:featuredmedia`` media object
  (``meta`` never exposes a logo URL itself).
* **Location / contract / remote** -- ``meta._job_location`` is free text
  ("Bamako", "Mali", "Sur site", ""), the contract type is the
  ``job-types``/``class_list`` taxonomy, and ``meta._remote_position`` is
  a 0/1 flag. All three are handled by the cleaner.
* **Salary** -- ``meta._job_salary`` (with ``_job_salary_currency`` and
  ``_job_salary_unit``) is the empty string on all 15 listings, so no
  amount is ever stated; the field is preserved in ``raw_payload`` only.
* **Dates** -- ``date`` is the WordPress post timestamp, parsed as aware
  UTC (the posting day is what is persisted); ``modified`` is the last
  edit. There is no exposed closing date (``_job_expires`` is not
  registered for REST), so the cleaner leaves ``closing_date`` None.
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from html import unescape

from pydantic import BaseModel, field_validator

#: The agency that runs the board. Used when a listing states no employer
#: (the model never guesses a client from the title).
DEFAULT_COMPANY_NAME = "ANPE Mali"

#: WP Job Manager stores the contract type as a ``job-types`` term; the
#: REST ``class_list`` renders it as ``job-type-<slug>``. The id->slug map
#: is the documented fallback for a response that omits ``class_list``.
JOB_TYPE_ID_TO_SLUG: dict[int, str] = {
    5: "cdi",
    6: "stage",
    7: "interim",
    8: "independant",
    9: "cdd",
}


def _text(value: object) -> str | None:
    """Trimmed non-empty string, or None -- tolerates ``"None"``/blank."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None":
        return None
    return text


def _nfkc(value: str | None) -> str | None:
    """Normalize compatibility characters (ligatures, Unicode spaces)."""
    return unicodedata.normalize("NFKC", value) if value else value


def _iso_datetime(value: object) -> datetime | None:
    """Parse a WordPress ``date``/``modified`` timestamp as aware UTC.

    WordPress returns a naive local timestamp (its configured timezone);
    the documented repo convention for naive source timestamps is UTC, and
    the posting *day* is what is persisted.
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


def _rendered(value: object) -> str | None:
    """The ``rendered`` field of a WordPress ``{rendered, protected}`` pair."""
    if isinstance(value, dict):
        return _text(value.get("rendered"))
    return _text(value)


def _embedded_logo(record: dict) -> str | None:
    """The company-logo URL from an embedded ``wp:featuredmedia`` object."""
    embedded = record.get("_embedded")
    if not isinstance(embedded, dict):
        return None
    media = embedded.get("wp:featuredmedia")
    if isinstance(media, list) and media and isinstance(media[0], dict):
        return _text(media[0].get("source_url"))
    return None


def _type_slugs(record: dict) -> list[str]:
    """Contract slugs from ``class_list`` (``job-type-<slug>`` entries)."""
    slugs: list[str] = []
    for entry in record.get("class_list") or []:
        if isinstance(entry, str) and entry.startswith("job-type-"):
            slug = entry[len("job-type-") :].strip()
            if slug:
                slugs.append(slug)
    return slugs


def _type_ids(record: dict) -> list[int]:
    """Contract term ids from ``job-types`` (the ``class_list`` fallback)."""
    ids: list[int] = []
    for value in record.get("job-types") or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


class RawAnpeMaliJob(BaseModel):
    """A single validated ANPE Mali job record (one WP Job Manager post).

    Attributes:
        source_job_id: WordPress post ``id``, stringified.
        job_title: ``title.rendered``, NFKC-normalized and unescaped.
        company_name: ``meta._company_name``, or ``DEFAULT_COMPANY_NAME``.
        company_logo_url: The embedded ``wp:featuredmedia`` source URL, if
            the listing has one.
        location_raw: ``meta._job_location`` free text, untouched.
        application: ``meta._application`` -- usually an e-mail address.
        remote_position: ``meta._remote_position`` as a bool.
        employment_type_slugs: ``job-type-*`` slugs from ``class_list``.
        job_type_ids: ``job-types`` term ids (used when slugs are absent).
        description_html: ``content.rendered`` -- the full notice HTML.
        posting_date: ``date`` parsed as aware UTC.
        modified_date: ``modified`` parsed as aware UTC.
        original_url: ``link`` -- the public notice page.
        raw_payload: The complete listing object, for audit.
    """

    source_job_id: str
    job_title: str
    company_name: str = DEFAULT_COMPANY_NAME
    company_logo_url: str | None = None
    location_raw: str | None = None
    application: str | None = None
    remote_position: bool = False
    employment_type_slugs: list[str] = []
    job_type_ids: list[int] = []
    description_html: str | None = None
    posting_date: datetime | None = None
    modified_date: datetime | None = None
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
    def from_payload(cls, record: object) -> RawAnpeMaliJob:
        """Build the model from one WP Job Manager REST listing object.

        Raises:
            ValueError: If ``record`` is not a JSON object or lacks a
                usable id/title/link (the parser turns that into a skip).
        """
        if not isinstance(record, dict):
            raise ValueError(f"listing must be a JSON object, got {type(record).__name__}")

        post_id = _text(record.get("id"))
        if post_id is None:
            raise ValueError("listing carries no id")

        title = _nfkc(_rendered(record.get("title")))
        if title is not None:
            title = unescape(title)

        meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
        company = _text(meta.get("_company_name")) or DEFAULT_COMPANY_NAME

        return cls(
            source_job_id=post_id,
            job_title=title or "",
            company_name=company,
            company_logo_url=_embedded_logo(record),
            location_raw=_text(meta.get("_job_location")),
            application=_text(meta.get("_application")),
            remote_position=bool(meta.get("_remote_position") or 0),
            employment_type_slugs=_type_slugs(record),
            job_type_ids=_type_ids(record),
            description_html=_rendered(record.get("content")),
            posting_date=_iso_datetime(record.get("date")),
            modified_date=_iso_datetime(record.get("modified")),
            original_url=_text(record.get("link")) or "",
            raw_payload=record,
        )
