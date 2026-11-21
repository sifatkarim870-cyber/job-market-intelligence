"""Typed model for a single raw BLMIS job record.

Mirrors the role ``scrapers/bdjobs_com/models.py`` plays: the raw,
source-specific shape -- one record from the Livewire ``wire:initial-data``
blob -- one step before ``cleaning/blmis_bt_cleaner.py`` maps it onto the
shared ``CleanedJob``.

Field facts confirmed live (2026-11-21; the worked record in
``tests/unit/scrapers/test_blmis_bt.py`` is a real one, ``application_no``
``42015747``):

* **Identity** -- ``application_no`` is the stable ``source_job_id`` and
  the public detail page is
  ``https://www.blmis.gov.bt/jobseeker_page/jobdetails/<application_no>``
  (the SPA's own detail route), which is what ``original_url`` stores.
* **Titles/company** -- ``designation`` is the title; the employer is
  ``company_name`` when present, else ``business_name`` (both null on a
  minority of rows, where ``placement`` -- the named workplace -- is the
  only employer-ish string).
* **Description** -- ``job_description`` is the body; ``qualification``,
  ``eligible_criteria``, ``terms_conditon`` (the site's own spelling) and
  ``remarks`` are further prose blobs carried separately so the cleaner can
  fold them in.
* **Location** -- ``dzongkhag_name`` is the district ("Thimphu",
  "Chukha") and ``gewog_name`` the sub-district ("Phuntsholing Throm");
  either may be null.
* **Dates** -- ``created_at`` is the posting date (``"2026-11-19
  09:23:25"``) and ``last_date_registration`` the closing date
  (``"2026-12-10"``). Naive values are assumed UTC (the documented repo
  convention).
* **Salary** -- ``starting_salary`` is a single monthly figure
  (``"16000.00"``); there is no upper bound and no currency code in the
  payload. The model keeps the number raw; the cleaner applies the
  positive-only rule, the currency convention and the open upper bound.
* **Employment** -- ``employment_type`` is prose ("Regular",
  "Contract"); the model keeps it raw so the cleaner maps it onto
  ``ref.employment_types``.
* **Overseas postings** -- ``vacancy_type_id`` 516 marks an overseas
  posting whose destination country is named in ``placement`` (e.g.
  "Qatar"); those rows are flagged here so the cleaner can treat their
  location and salary currency differently from domestic rows.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, field_validator

#: The two server-rendered timestamp shapes on the board.
_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")

#: ``vacancy_type_id`` that marks an overseas ("Oversea Vacancies") posting.
OVERSEA_VACANCY_TYPE_ID = 516


def _text(value: object) -> str | None:
    """Trimmed non-empty string, or None -- tolerates ``"None"``/blank."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None":
        return None
    return text


def _int(value: object) -> int | None:
    """Coerce to int, or None when unparseable/absent (keeps 0)."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _float(value: object) -> float | None:
    """Coerce to float, or None when unparseable/absent (keeps 0.0)."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: object) -> datetime | None:
    """Parse a board date as aware UTC.

    Accepts ``"2026-11-19 09:23:25"`` and ``"2026-12-10"``; naive values
    are assumed UTC (documented convention). Unparseable values become
    ``None`` -- honest absence rather than a crash.
    """
    text = _text(value)
    if text is None:
        return None
    parsed: datetime | None = None
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _compose_location(
    gewog: str | None,
    dzongkhag: str | None,
    placement: str | None,
    *,
    is_oversea: bool,
) -> str | None:
    """Build the raw location string from the board's location fields.

    An overseas posting names its destination country in ``placement``
    ("Qatar"), so that wins; a domestic posting names a sub-district
    and/or district ("Phuntsholing Throm, Chukha"), joined most-specific
    first.
    """
    if is_oversea and placement:
        return placement
    parts = [part for part in (gewog, dzongkhag) if part]
    if parts:
        return ", ".join(parts)
    return None


class RawBlmisJob(BaseModel):
    """A single validated BLMIS job record.

    Attributes:
        source_job_id: The job's ``application_no``, stringified.
        job_title: ``designation``.
        company_name: ``company_name`` -> ``business_name`` -> the named
            ``placement`` when nothing else names the employer.
        location_text: Sub-district/district for a domestic posting, or the
            destination country for an overseas one.
        description_raw: ``job_description``.
        qualification_raw: ``qualification`` (e.g. "Diploma").
        eligibility_raw: ``eligible_criteria`` when present.
        terms_raw: ``terms_conditon`` (the site's spelling) when present.
        remarks_raw: ``remarks`` when present.
        category_raw: ``job_category`` (the board's occupation label).
        employment_type_raw: ``employment_type`` ("Regular"/"Contract").
        salary_min_raw: ``starting_salary`` as a number, still raw.
        vacancies: ``slot`` (0 meaning "unstated").
        posting_date: ``created_at``.
        closing_date: ``last_date_registration``.
        is_oversea: True for an overseas posting.
        country_text: The destination country named in ``placement`` for an
            overseas posting, else None.
        original_url: The public detail page URL.
        raw_payload: The source record dict, for audit.
    """

    source_job_id: str
    job_title: str
    company_name: str
    location_text: str | None = None
    description_raw: str | None = None
    qualification_raw: str | None = None
    eligibility_raw: str | None = None
    terms_raw: str | None = None
    remarks_raw: str | None = None
    category_raw: str | None = None
    employment_type_raw: str | None = None
    salary_min_raw: float | None = None
    vacancies: int | None = None
    posting_date: datetime | None = None
    closing_date: datetime | None = None
    is_oversea: bool = False
    country_text: str | None = None
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
        record: object,
        *,
        original_url: str,
        is_oversea: bool = False,
    ) -> RawBlmisJob:
        """Build the model from one ``wire:initial-data`` vacancy record.

        Args:
            record: The vacancy dict from a ``job_by_*`` array (required --
                it carries the id).
            original_url: The public detail page URL.
            is_oversea: True when the record came from the overseas facet
                or carries ``vacancy_type_id`` 516.

        Raises:
            ValueError: If ``record`` is not a JSON object or carries no
                ``application_no``.
        """
        if not isinstance(record, dict):
            raise ValueError(f"record must be a JSON object, got {type(record).__name__}")

        job_id = _text(record.get("application_no"))
        if job_id is None:
            raise ValueError("record carries no application_no")

        oversea = is_oversea or _int(record.get("vacancy_type_id")) == OVERSEA_VACANCY_TYPE_ID

        dzongkhag = _text(record.get("dzongkhag_name"))
        gewog = _text(record.get("gewog_name"))
        placement = _text(record.get("placement"))

        company = (
            _text(record.get("company_name"))
            or _text(record.get("business_name"))
            or (placement if not oversea else None)
            or ""
        )

        return cls(
            source_job_id=job_id,
            job_title=_text(record.get("designation")) or "",
            company_name=company,
            location_text=_compose_location(gewog, dzongkhag, placement, is_oversea=oversea),
            description_raw=_text(record.get("job_description")),
            qualification_raw=_text(record.get("qualification")),
            eligibility_raw=_text(record.get("eligible_criteria")),
            terms_raw=_text(record.get("terms_conditon")),
            remarks_raw=_text(record.get("remarks")),
            category_raw=_text(record.get("job_category")),
            employment_type_raw=_text(record.get("employment_type")),
            salary_min_raw=_float(record.get("starting_salary")),
            vacancies=_int(record.get("slot")),
            posting_date=_parse_date(record.get("created_at")),
            closing_date=_parse_date(record.get("last_date_registration")),
            is_oversea=oversea,
            country_text=placement if oversea else None,
            original_url=original_url,
            raw_payload=record,
        )
