"""Typed model for a single raw XpressJobs job record.

Mirrors the role ``scrapers/zangia_mn/models.py`` plays: the raw,
source-specific shape -- one listing row merged with its detail record --
one step before ``cleaning/xpress_jobs_cleaner.py`` maps it onto the
shared ``CleanedJob``.

Field facts confirmed live (2026-11-28; worked example in
``tests/unit/scrapers/test_xpress_jobs.py`` is jobId ``357454``):

* **Identity** -- ``jobId`` is a stable integer on both the listing row
  and the detail; it is stringified into ``source_job_id``. The public ad
  URL is ``https://xpress.jobs/jobs/view/<jobId>``.
* **Titles/company** -- ``jobTitle`` on both records; the employer is
  ``organizationName`` (listing) / ``organization.organizationName``
  (detail). Both agree on the sample.
* **Description** -- the detail carries ``jobInfo`` (HTML). The listing's
  ``overview`` is only a one-line teaser, so the model prefers the detail
  body and keeps ``overview`` in ``raw_payload``.
* **Location** -- ``locations`` is a free-text string like
  ``" Colombo, Western Province"``, and may hold several places separated
  by ``"; "``. It is kept as the raw location text; the cleaner and the
  geographic resolver do the interpreting.
* **Dates** -- the listing's ``createdDate`` is always ``null``; only the
  detail carries the real ISO-8601 ``createdDate`` (e.g.
  ``"2026-11-27T01:57:26.667"``, no timezone). ``expiryDateOnWebsite`` is
  the closing date on both records.
* **Salary** -- ``minSalary``/``maxSalary`` are **strings**: the literal
  ``"Any"`` when the board hides the figure, otherwise a whole-LKR number
  (e.g. ``"40000"``), plus a placeholder ``"1"`` used alongside "Any".
  ``salaryRange`` repeats it as display text. The model keeps the parsed
  integers; the cleaner applies the "1 means hidden" rule.
* **Employment** -- ``jobType`` on both records, observed as
  ``"Full-Time"``, ``"Permanent"`` and ``"Contract Basis"``. The cleaner
  maps it onto ``ref.employment_types``.
* **Remote** -- ``remote`` is a boolean flag on the listing row.
* **Categories** -- ``sectors`` (detail) is a list of
  ``{sectorId, sectorName, friendlyName}`` labels. They are job
  categories, not skills, so they are kept in ``raw_payload`` rather than
  forced into the ``skills`` list.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator


def _text(value: object) -> str | None:
    """Trimmed non-empty string, or None -- tolerates ``"None"``/blank."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"None", "null"}:
        return None
    return text


def _salary_int(value: object) -> int | None:
    """A ``minSalary``/``maxSalary`` string -> whole LKR, or None.

    The board hides a figure two ways: the literal ``"Any"`` and a
    placeholder bound of ``1``. Both become ``None`` here so the cleaner
    never stores a 1-LKR salary; a real whole-LKR amount passes through.
    """
    text = _text(value)
    if text is None:
        return None
    if text.lower() in {"any", "n/a", "na", "negotiable"}:
        return None
    try:
        amount = int(float(text.replace(",", "")))
    except (TypeError, ValueError):
        return None
    return amount if amount > 1 else None


def _datetime(value: object) -> datetime | None:
    """An ISO-8601 string -> a naive datetime, or None.

    XpressJobs timestamps carry no timezone offset (``"2026-11-27T01:57:26
    .667"``), so they are kept naive rather than stamped with a guessed
    zone; ``core.jobs.posting_date``/``closing_date`` are SQL ``DATE``
    columns anyway.
    """
    text = _text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _sector_names(value: object) -> list[str]:
    """A JSON array of sector objects -> their ``sectorName`` labels."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("sectorName")) or _text(item.get("friendlyName"))
        if name:
            out.append(name)
    return out


class RawXpressJob(BaseModel):
    """A single validated XpressJobs record (merged listing + detail).

    Attributes:
        source_job_id: The posting's ``jobId``, stringified.
        job_title: ``jobTitle``.
        company_name: ``organization.organizationName`` (detail) ->
            ``organizationName`` (listing).
        company_logo_url: ``logoImageUrl`` when ``hasLogo`` is true.
        description_html: ``jobInfo`` (detail) -- the only HTML body.
        location_text: ``locations`` (listing) -> ``jobItem.locations``.
        posting_date: The detail's ISO ``createdDate`` (the listing's is
            always null), as a naive datetime.
        closing_date: ``expiryDateOnWebsite`` (listing) -> ``jobItem``.
        employment_type_raw: ``jobType`` -- "Full-Time"/"Permanent"/
            "Contract Basis"; the cleaner maps it.
        salary_min_raw / salary_max_raw: ``minSalary``/``maxSalary`` parsed
            to whole LKR (``"Any"`` and the placeholder ``1`` -> None).
        is_remote: The listing's ``remote`` boolean flag.
        original_url: ``https://xpress.jobs/jobs/view/<jobId>``.
        raw_payload: ``{"listing": ..., "detail": ...}`` for audit.
    """

    source_job_id: str
    job_title: str
    company_name: str
    company_logo_url: str | None = None
    description_html: str | None = None
    location_text: str | None = None
    posting_date: datetime | None = None
    closing_date: datetime | None = None
    employment_type_raw: str | None = None
    salary_min_raw: int | None = None
    salary_max_raw: int | None = None
    is_remote: bool = False
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
    ) -> RawXpressJob:
        """Build the model from one listing row plus its detail record.

        Args:
            listing: The listing row dict (required -- it carries the
                ``jobId`` used for the detail fetch and the public URL).
            detail: The detail dict, or None when the detail GET failed
                (the listing-only fields still make a usable record).
            original_url: The public ``https://xpress.jobs/jobs/view/<id>``
                URL.

        Raises:
            ValueError: If ``listing`` is not a JSON object (the parser
                turns that into a skip).
        """
        if not isinstance(listing, dict):
            raise ValueError(f"listing must be a JSON object, got {type(listing).__name__}")
        detail_dict = detail if isinstance(detail, dict) else {}
        job_item = detail_dict.get("jobItem")
        job_item = job_item if isinstance(job_item, dict) else {}
        organization = detail_dict.get("organization")
        organization = organization if isinstance(organization, dict) else {}

        logo_url = _text(listing.get("logoImageUrl")) or _text(organization.get("logoImageUrl"))
        has_logo = bool(listing.get("hasLogo")) or bool(organization.get("hasLogo"))
        if not has_logo:
            logo_url = None

        return cls(
            source_job_id=str(listing.get("jobId") or detail_dict.get("jobId") or ""),
            job_title=_text(detail_dict.get("jobTitle"))
            or _text(listing.get("jobTitle"))
            or "",
            company_name=_text(organization.get("organizationName"))
            or _text(detail_dict.get("organizationName"))
            or _text(listing.get("organizationName"))
            or "",
            company_logo_url=logo_url,
            description_html=_text(detail_dict.get("jobInfo")),
            location_text=_text(listing.get("locations"))
            or _text(job_item.get("locations")),
            posting_date=_datetime(detail_dict.get("createdDate"))
            or _datetime(listing.get("createdDate")),
            closing_date=_datetime(listing.get("expiryDateOnWebsite"))
            or _datetime(job_item.get("expiryDateOnWebsite")),
            employment_type_raw=_text(listing.get("jobType"))
            or _text(job_item.get("jobType")),
            salary_min_raw=_salary_int(detail_dict.get("minSalary")),
            salary_max_raw=_salary_int(detail_dict.get("maxSalary")),
            is_remote=bool(listing.get("remote") or job_item.get("remote")),
            original_url=original_url,
            raw_payload={
                "listing": listing,
                "detail": detail_dict,
                "sectors": _sector_names(detail_dict.get("sectors")),
                "overview": _text(listing.get("overview")),
                "education": _text(detail_dict.get("education")),
                "experience": _text(detail_dict.get("experience")),
                "salary_range_text": _text(detail_dict.get("salaryRange")),
            },
        )
