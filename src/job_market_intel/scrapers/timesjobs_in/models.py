"""Typed model for a single raw TimesJobs job record.

Mirrors the role ``scrapers/irantalent/models.py`` plays: the raw,
source-specific shape -- one merged listing row plus its detail record --
one step before ``cleaning/timesjobs_in_cleaner.py`` maps it onto the
shared ``CleanedJob``.

Field facts confirmed live (2026-11-21; listing row 81077785 and its
detail record are the worked examples in
``tests/unit/scrapers/test_timesjobs_in.py``):

* **Identity** -- ``jobId`` is the job id (a string in the listing, an int
  in the detail); it is the stable ``source_job_id``. The detail URL is
  derived from the listing's own ``jobDetailUrl`` (the text after
  ``jobid-``), not stored separately.
* **Titles/company** -- ``title`` and ``company`` on the listing;
  ``title`` and ``companyName`` on the detail. Both agree on the sample;
  the model prefers the detail and falls back to the listing.
* **Description** -- the detail ``description`` is full HTML (median
  ~4.8 KB across 30 sampled rows, range 381-10,273 chars); the listing
  ``description`` is truncated to ~220-250 chars with a trailing "...".
  ``desiredCandidate`` and ``perks`` are also HTML/plain blobs and are
  carried separately so the cleaner can decide how to fold them in.
* **Skills** -- a single string of space-separated phrases separated by
  runs of whitespace (``"Financial Analysis   Performance Reporting"``),
  split on 2+ spaces.
* **Dates** -- ``postedAt`` is a naive timestamp (``"2026-11-19T22:49:34"``)
  and ``postDate`` a plain date (``"2026-11-19"``); ``expiresAt`` is
  date-only. Naive timestamps are assumed UTC (same documented convention
  the other sources' models use).
* **Salary** -- ``minCtc``/``maxCtc`` are whole INR, but every sampled
  detail row carried ``hideCtcFromCandidate: true`` with ``-1`` bounds, so
  the raw model keeps the numbers and the cleaner applies the
  hide/zero/unstated rules.
* **Employment vs. work mode** -- the detail ``employmentType`` is
  usually ``"Full-time"`` but occasionally ``"On-site"``; the detail
  ``jobType`` is always ``"On-site"``. The model keeps both raw so the
  cleaner can map the first onto ``ref.employment_types`` and the second
  onto ``ref.remote_work_types``.
* **Experience** -- ``minExperience``/``maxExperience`` are integers
  (0 meaning "unstated").
* **Tags** -- the detail offers four labeled arrays (``functionNames``,
  ``aosNames``, ``roleNames``, ``industryNames``); all are merged into
  ``function_raws`` and cleaned/deduplicated downstream.
* **Education** -- ``graduationCourseNames`` / ``postgraduationCourseNames``
  are string arrays; the model keeps them as ``education_raws`` (the
  raw model makes no level judgment -- the cleaner does).
* **Location** -- ``locationNames`` is a list of city/country strings
  (e.g. ``["Other City(s) in New York", "Richmond"]``); ``locationOthers``
  is a free-text supplement. The listing carries a single ``location``
  string as a fallback.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, field_validator

#: The board separates distinct skill phrases with runs of whitespace
#: (single spaces inside a phrase), so 2+ spaces is the split delimiter.
_SKILL_SPLIT = re.compile(r"\s{2,}")


def _text(value: object) -> str | None:
    """Trimmed non-empty string, or None -- tolerates ``"None"``/blank."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None":
        return None
    return text


def _int(value: object) -> int | None:
    """Coerce to int, or None when unparseable/absent (keeps ``-1``)."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _iso_date(value: object) -> datetime | None:
    """Parse TimesJobs timestamps (``"2026-11-19T22:49:34"`` and
    ``"2026-11-19"`` both observed).

    Naive timestamps are assumed UTC (documented convention). Unparseable
    values become ``None`` -- honest absence rather than a crash.
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


def _str_list(value: object) -> list[str]:
    """A JSON array of strings -> trimmed non-empty labels, first-seen order."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _text(item)
        if text:
            out.append(text)
    return out


def _split_skills(value: object) -> list[str]:
    """Split the board's whitespace-run-separated skill string."""
    text = _text(value)
    if not text:
        return []
    return [part.strip() for part in _SKILL_SPLIT.split(text) if part.strip()]


class RawTimesjobsJob(BaseModel):
    """A single validated TimesJobs job record (merged listing + detail).

    Attributes:
        source_job_id: The job's ``jobId``, stringified.
        job_title: ``title`` -- the board publishes only English titles.
        company_name: ``companyName`` (detail) -> ``company`` (listing).
        company_logo_url: ``companyLogo`` from whichever record carries
            one (the detail row is null more often than the listing).
        description_html: Full HTML ``description`` (detail); None when
            the detail was unavailable or the poster left it empty.
        desired_candidate_html: HTML ``desiredCandidate`` when present.
        perks_raw: Free-text ``perks`` when present.
        skills_raw: Skill phrases split from the ``skills`` string.
        location_text: ``locationNames`` + ``locationOthers`` joined, or
            the listing's single ``location`` string as a fallback.
        posting_date: ``postedAt`` (detail) -> ``postDate`` (listing).
        closing_date: ``expiresAt`` (detail) -> ``expiryDate`` (listing).
        employment_type_raw: ``employmentType`` (detail) -- usually
            "Full-time", occasionally "On-site"; the cleaner maps it.
        work_mode_raw: ``jobType`` -- "On-site" on every sampled row.
        salary_min_raw / salary_max_raw: ``minCtc``/``maxCtc`` in whole
            INR (the cleaner applies the hide/zero/unstated rules).
        salary_show_flag: ``not hideCtcFromCandidate`` when the detail
            states a boolean; None otherwise (treated as "no statement").
        experience_years_min / experience_years_max: ``minExperience``/
            ``maxExperience`` (0 meaning "unstated"; the cleaner drops 0).
        function_raws: ``functionNames`` + ``aosNames`` + ``roleNames`` +
            ``industryNames`` -- the labeled tag sources.
        education_raws: ``graduationCourseNames`` +
            ``postgraduationCourseNames``.
        vacancies: ``vacancies`` (0 meaning "unstated").
        apply_url: ``externalJobsLink`` -- the employer's own application
            page, when the posting carries one.
        original_url: The listing's ``jobDetailUrl`` (the public site URL).
        raw_payload: ``{"listing": ..., "detail": ...}`` for audit.
    """

    source_job_id: str
    job_title: str
    company_name: str
    company_logo_url: str | None = None
    description_html: str | None = None
    desired_candidate_html: str | None = None
    perks_raw: str | None = None
    skills_raw: list[str] = []
    location_text: str | None = None
    posting_date: datetime | None = None
    closing_date: datetime | None = None
    employment_type_raw: str | None = None
    work_mode_raw: str | None = None
    salary_min_raw: int | None = None
    salary_max_raw: int | None = None
    salary_show_flag: bool | None = None
    experience_years_min: int | None = None
    experience_years_max: int | None = None
    function_raws: list[str] = []
    education_raws: list[str] = []
    vacancies: int | None = None
    apply_url: str | None = None
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
    ) -> RawTimesjobsJob:
        """Build the model from one listing row plus its detail record.

        Args:
            listing: The listing row dict (required -- it carries the id
                and the detail token).
            detail: The detail dict, or None when the detail GET failed
                (the listing-only fields still make a usable record).
            original_url: The listing's ``jobDetailUrl``.

        Raises:
            ValueError: If ``listing`` is not a JSON object (the parser
                turns that into a skip).
        """
        if not isinstance(listing, dict):
            raise ValueError(f"listing must be a JSON object, got {type(listing).__name__}")
        detail_dict = detail if isinstance(detail, dict) else {}

        location_names = _str_list(detail_dict.get("locationNames"))
        location_others = _text(detail_dict.get("locationOthers"))
        if location_others:
            location_names.append(location_others)
        location_text = ", ".join(location_names) or _text(listing.get("location"))

        skills = _split_skills(detail_dict.get("skills")) or _split_skills(listing.get("skills"))

        function_raws = (
            _str_list(detail_dict.get("functionNames"))
            + _str_list(detail_dict.get("aosNames"))
            + _str_list(detail_dict.get("roleNames"))
            + _str_list(detail_dict.get("industryNames"))
        )
        education_raws = _str_list(detail_dict.get("graduationCourseNames")) + _str_list(
            detail_dict.get("postgraduationCourseNames")
        )

        hide_ctc = detail_dict.get("hideCtcFromCandidate")
        salary_show_flag = (not hide_ctc) if isinstance(hide_ctc, bool) else None

        return cls(
            source_job_id=str(listing.get("jobId") or detail_dict.get("jobId") or ""),
            job_title=_text(detail_dict.get("title")) or _text(listing.get("title")) or "",
            company_name=_text(detail_dict.get("companyName"))
            or _text(listing.get("company"))
            or "",
            company_logo_url=_text(detail_dict.get("companyLogo"))
            or _text(listing.get("companyLogo")),
            description_html=_text(detail_dict.get("description")),
            desired_candidate_html=_text(detail_dict.get("desiredCandidate")),
            perks_raw=_text(detail_dict.get("perks")),
            skills_raw=skills,
            location_text=location_text,
            posting_date=_iso_date(detail_dict.get("postedAt"))
            or _iso_date(listing.get("postDate")),
            closing_date=_iso_date(detail_dict.get("expiresAt"))
            or _iso_date(listing.get("expiryDate")),
            employment_type_raw=_text(detail_dict.get("employmentType")),
            work_mode_raw=_text(detail_dict.get("jobType")) or _text(listing.get("jobType")),
            salary_min_raw=_int(detail_dict.get("minCtc")),
            salary_max_raw=_int(detail_dict.get("maxCtc")),
            salary_show_flag=salary_show_flag,
            experience_years_min=_int(detail_dict.get("minExperience")),
            experience_years_max=_int(detail_dict.get("maxExperience")),
            function_raws=function_raws,
            education_raws=education_raws,
            vacancies=_int(detail_dict.get("vacancies")),
            apply_url=_text(detail_dict.get("externalJobsLink")),
            original_url=original_url,
            raw_payload={"listing": listing, "detail": detail_dict},
        )
