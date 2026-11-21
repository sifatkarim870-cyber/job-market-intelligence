"""Typed model for a single raw Bdjobs job record.

Mirrors the role ``scrapers/timesjobs_in/models.py`` plays: the raw,
source-specific shape -- one merged search row plus its detail record --
one step before ``cleaning/bdjobs_com_cleaner.py`` maps it onto the shared
``CleanedJob``.

Field facts confirmed live (2026-11-21; search row ``1558863`` and its
detail record are the worked examples in
``tests/unit/scrapers/test_bdjobs_com.py``):

* **Identity** -- the search row carries ``Jobid`` (string) and the detail
  ``JobId`` (same value); it is the stable ``source_job_id``. The public
  detail page is ``https://bdjobs.com/h/details/<id>`` (the SPA's
  ``jobDetailsBaseUrl``), which is what ``original_url`` stores.
* **Titles/company** -- the search row carries ``jobTitle`` /
  ``companyName`` and the detail ``JobTitle`` / ``CompnayName`` (note the
  site's own misspelling) plus the correct ``CompanyNameENG``. The model
  prefers ``CompanyNameENG``, then ``CompnayName``, then the search row.
* **Description** -- the search ``jobDescription`` is truncated (it often
  just repeats ``eduRec``); the detail ``JobDescription`` is the full HTML
  notice. ``AdditionJobRequirements`` and ``JobOtherBenifits`` are further
  HTML blobs carried separately so the cleaner can fold them in.
* **Skills** -- the detail ``SkillsRequired`` is a single
  comma-and-space separated string (e.g. ``"Access Control, CCTV, LAN/ WAN"``);
  ``SuggestedSkills`` uses the same shape.
* **Dates** -- the search row carries ISO ``publishDate`` /
  ``deadlineDB`` (``"2026-11-21T11:25:00Z"``); the detail carries the
  human ``PostedOn`` / ``Deadline`` (``"Nov 21, 2026"``) and ISO
  ``DeadlineDB`` (``"2026-12-04"``). Naive values are assumed UTC (the
  documented repo convention).
* **Salary** -- the detail carries ``JobSalaryMinSalary`` /
  ``JobSalaryMaxSalary`` (whole BDT, ``"0"`` when unstated),
  ``JobSalaryRange`` / ``JobSalaryRangeText`` (``"Tk. 20000 - 30000
  (Monthly)"``, ``"Negotiable"`` or ``"--"``) and ``ShowSalary``
  (``"1"``/``"0"``). The model keeps the numbers and the flag raw; the
  cleaner applies the show/zero/negotiable rules.
* **Employment vs. work mode** -- the detail ``JobNature`` is usually
  ``"Full Time"``; ``JobWorkPlace`` is ``"Work at office"``,
  ``"Work from home"`` or blank. The model keeps both raw so the cleaner
  can map the first onto ``ref.employment_types`` and the second onto
  ``ref.remote_work_types``.
* **Experience** -- the detail ``experience`` is an HTML blurb
  (``"<ul><li>At least 5 years</li>..."``) that the cleaner parses for a
  year range; the raw HTML is preserved here.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, field_validator

#: The board separates distinct skills with a comma; some entries keep an
#: internal space or slash ("LAN/ WAN").
_SKILL_SPLIT = re.compile(r"\s*,\s*")

#: The board's human dates look like "Nov 21, 2026".
_ENGLISH_DATE_FORMATS = ("%b %d, %Y", "%d %b %Y")


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


def _bool_flag(value: object) -> bool | None:
    """Map the site's ``"1"``/``"0"`` string flag to a bool, else None."""
    text = _text(value)
    if text == "1":
        return True
    if text == "0":
        return False
    text_lower = (text or "").lower()
    if text_lower == "true":
        return True
    if text_lower == "false":
        return False
    return None


def _parse_date(value: object) -> datetime | None:
    """Parse an ISO (``"2026-12-04"``/``"2026-11-21T11:25:00Z"``) or the
    board's human (``"Nov 21, 2026"``) date as aware UTC.

    Naive values are assumed UTC (documented convention). Unparseable
    values become ``None`` -- honest absence rather than a crash.
    """
    text = _text(value)
    if text is None:
        return None
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in _ENGLISH_DATE_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _split_skills(value: object) -> list[str]:
    """Split the board's comma-separated skill string, first-seen order."""
    text = _text(value)
    if not text:
        return []
    out: list[str] = []
    for part in _SKILL_SPLIT.split(text):
        part = part.strip()
        if part:
            out.append(part)
    return out


class RawBdjobsJob(BaseModel):
    """A single validated Bdjobs job record (merged search row + detail).

    Attributes:
        source_job_id: The job's ``Jobid``/``JobId``, stringified.
        job_title: ``JobTitle`` (detail) -> ``jobTitle`` (search row).
        company_name: ``CompanyNameENG`` -> ``CompnayName`` -> search
            ``companyName``.
        company_logo_url: ``JobLOgoName`` (detail, a full URL) ->
            ``logoUrl`` (search row).
        description_html: Full HTML ``JobDescription`` (detail).
        requirements_html: HTML ``AdditionJobRequirements`` when present.
        benefits_html: HTML ``JobOtherBenifits`` when present.
        education_html: HTML ``EducationRequirements`` when present.
        skills_raw: Skill phrases split from ``SkillsRequired`` plus
            ``SuggestedSkills``.
        location_text: ``JobLocation`` (detail) -> ``location`` (search).
        posting_date: Search ``publishDate`` -> detail ``PostedOn``.
        closing_date: Search ``deadlineDB`` -> detail ``DeadlineDB`` ->
            detail ``Deadline``.
        employment_type_raw: ``JobNature`` (detail) -> ``JobType`` (search).
        work_mode_raw: ``JobWorkPlace`` (detail) -> ``WorkPlace`` (search).
        salary_min_raw / salary_max_raw: ``JobSalaryMinSalary`` /
            ``JobSalaryMaxSalary`` in whole BDT (0 meaning "unstated").
        salary_show_flag: ``ShowSalary`` -> bool when the detail states it,
            None otherwise.
        salary_text_raw: ``JobSalaryRange`` / ``JobSalaryRangeText``.
        experience_text_raw: HTML ``experience`` blurb (parsed downstream).
        vacancies: ``JobVacancies`` (0 meaning "unstated").
        apply_url: ``ApplyURL`` or a ``mailto:`` built from
            ``JobAppliedEmail``, when the posting carries one.
        original_url: The public detail page URL.
        raw_payload: ``{"listing": ..., "detail": ...}`` for audit.
    """

    source_job_id: str
    job_title: str
    company_name: str
    company_logo_url: str | None = None
    description_html: str | None = None
    requirements_html: str | None = None
    benefits_html: str | None = None
    education_html: str | None = None
    skills_raw: list[str] = []
    location_text: str | None = None
    posting_date: datetime | None = None
    closing_date: datetime | None = None
    employment_type_raw: str | None = None
    work_mode_raw: str | None = None
    salary_min_raw: int | None = None
    salary_max_raw: int | None = None
    salary_show_flag: bool | None = None
    salary_text_raw: str | None = None
    experience_text_raw: str | None = None
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
    ) -> RawBdjobsJob:
        """Build the model from one search row plus its detail record.

        Args:
            listing: The search row dict (required -- it carries the id).
            detail: The detail dict, or None when the detail GET failed
                (the search-only fields still make a usable record).
            original_url: The public detail page URL.

        Raises:
            ValueError: If ``listing`` is not a JSON object (the parser
                turns that into a skip) or carries no id.
        """
        if not isinstance(listing, dict):
            raise ValueError(f"listing must be a JSON object, got {type(listing).__name__}")
        detail_dict = detail if isinstance(detail, dict) else {}

        job_id = _text(listing.get("Jobid")) or _text(detail_dict.get("JobId"))
        if job_id is None:
            raise ValueError("listing carries no Jobid")

        apply_url = _text(detail_dict.get("ApplyURL"))
        if apply_url is None:
            email = _text(detail_dict.get("JobAppliedEmail"))
            if email and "@" in email:
                apply_url = f"mailto:{email}"

        return cls(
            source_job_id=job_id,
            job_title=_text(detail_dict.get("JobTitle")) or _text(listing.get("jobTitle")) or "",
            company_name=_text(detail_dict.get("CompanyNameENG"))
            or _text(detail_dict.get("CompnayName"))
            or _text(listing.get("companyName"))
            or "",
            company_logo_url=_text(detail_dict.get("JobLOgoName")) or _text(listing.get("logoUrl")),
            description_html=_text(detail_dict.get("JobDescription")),
            requirements_html=_text(detail_dict.get("AdditionJobRequirements")),
            benefits_html=_text(detail_dict.get("JobOtherBenifits")),
            education_html=_text(detail_dict.get("EducationRequirements")),
            skills_raw=_split_skills(detail_dict.get("SkillsRequired"))
            + _split_skills(detail_dict.get("SuggestedSkills")),
            location_text=_text(detail_dict.get("JobLocation")) or _text(listing.get("location")),
            posting_date=_parse_date(listing.get("publishDate"))
            or _parse_date(detail_dict.get("PostedOn")),
            closing_date=_parse_date(listing.get("deadlineDB"))
            or _parse_date(detail_dict.get("DeadlineDB"))
            or _parse_date(detail_dict.get("Deadline")),
            employment_type_raw=_text(detail_dict.get("JobNature"))
            or _text(listing.get("JobType")),
            work_mode_raw=_text(detail_dict.get("JobWorkPlace")) or _text(listing.get("WorkPlace")),
            salary_min_raw=_int(detail_dict.get("JobSalaryMinSalary")),
            salary_max_raw=_int(detail_dict.get("JobSalaryMaxSalary")),
            salary_show_flag=_bool_flag(detail_dict.get("ShowSalary")),
            salary_text_raw=_text(detail_dict.get("JobSalaryRange"))
            or _text(detail_dict.get("JobSalaryRangeText")),
            experience_text_raw=_text(detail_dict.get("experience")),
            vacancies=_int(detail_dict.get("JobVacancies")),
            apply_url=apply_url,
            original_url=original_url,
            raw_payload={"listing": listing, "detail": detail_dict},
        )
