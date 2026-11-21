"""Cleans validated Bdjobs records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawBdjobsJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment calls
about meaning.

Bdjobs-specific quirks handled here:

* **Salary is often undisclosed.** ``JobSalaryMinSalary`` /
  ``JobSalaryMaxSalary`` are whole BDT and ``0`` when unstated; a row may
  be "Negotiable" (bounds ``0``) or carry ``ShowSalary == "0"``. The
  cleaner drops non-positive bounds, honors an explicit
  ``ShowSalary == 0`` as a site-side withhold, and swaps a reversed pair
  rather than dropping it. Currency is ``BDT`` and pay period is read from
  the range text (``"(Monthly)"`` observed on every disclosed row) with a
  monthly default, the Bangladesh convention.
* **Employment vs. work mode are separate fields.** ``JobNature`` is
  usually ``"Full Time"`` (else Contractual/Part Time); the cleaner maps
  the recognized labels onto ``ref.employment_types``.
  ``JobWorkPlace`` is ``"Work at office"``, ``"Work from home"`` or blank;
  the cleaner maps it onto ``ref.remote_work_types`` and falls back to the
  shared :func:`map_remote_work_type` for anything it does not recognize.
* **Descriptions are HTML** (``JobDescription`` plus the optional
  ``EducationRequirements``, ``AdditionJobRequirements`` and
  ``JobOtherBenifits``); all are folded into one cleaned description, since
  each is job content with no separate ``CleanedJob`` slot.
* **Experience is a prose blurb** (``"<ul><li>3 to 5 years</li>..."``),
  parsed here for a year range ("N to M years", "At least N years"),
  dropped when it only names a "business area".
* **Skills are a comma-separated string** in ``SkillsRequired`` /
  ``SuggestedSkills``; split and cleaned, lowercased and de-duplicated.
"""

from __future__ import annotations

import re

from loguru import logger

from job_market_intel.scrapers.bdjobs_com.models import RawBdjobsJob

from .common import CleanedJob
from .qualification_mappers import map_remote_work_type
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

#: ``JobNature`` (or the search row's ``JobType``) -> ref.employment_types.code.
_EMPLOYMENT_MAP = {
    "full time": "full_time",
    "fulltime": "full_time",
    "permanent": "full_time",
    "part time": "part_time",
    "parttime": "part_time",
    "contract": "contract",
    "contractual": "contract",
    "contract based": "contract",
    "temporary": "temporary",
    "temp": "temporary",
    "internship": "internship",
    "intern": "internship",
    "freelance": "freelance",
    "apprenticeship": "apprenticeship",
    "apprentice": "apprenticeship",
}

#: ``JobWorkPlace`` (or the search row's ``WorkPlace``) -> ref.remote_work_types.code.
#: "Work from home" is mapped to ``remote_country`` (remote within the
#: board's own country, Bangladesh) rather than the city/global variants --
#: no signal here narrows it further.
_WORK_MODE_MAP = {
    "work at office": "on_site",
    "work at office/on site": "on_site",
    "work from office": "on_site",
    "office": "on_site",
    "at office": "on_site",
    "work from home": "remote_country",
    "work from home/remote": "remote_country",
    "home": "remote_country",
    "remote": "remote_country",
    "hybrid": "hybrid",
    "work from anywhere": "remote_global",
}

#: ``(Monthly)``/``(Yearly)`` ... token -> ref pay_period.
_PAY_PERIOD_TOKENS = {
    "hourly": "hourly",
    "per hour": "hourly",
    "daily": "daily",
    "per day": "daily",
    "weekly": "weekly",
    "per week": "weekly",
    "monthly": "monthly",
    "per month": "monthly",
    "yearly": "yearly",
    "annually": "yearly",
    "annual": "yearly",
    "per year": "yearly",
}

#: Experience blurb patterns, applied in this order.
_EXP_RANGE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:to|-|\u2013)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)",
    re.IGNORECASE,
)
_EXP_AT_LEAST = re.compile(
    r"(?:at least|minimum|min\.?)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)",
    re.IGNORECASE,
)
_EXP_AT_MOST = re.compile(
    r"(?:at most|maximum|max\.?)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)",
    re.IGNORECASE,
)
_EXP_PLAIN = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE)


def _normalize(value: str) -> str:
    """Lowercase, hyphens/slashes/underscores -> spaces, collapse runs."""
    lowered = value.strip().lower().replace("-", " ").replace("/", " ").replace("_", " ")
    return re.sub(r"\s+", " ", lowered).strip()


def _clean_tags(raw_tags: list[str]) -> list[str]:
    """Clean, lowercase, and de-duplicate raw tags, preserving first-seen order."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw_tag in raw_tags:
        cleaned_tag = clean_plain_text(raw_tag)
        if not cleaned_tag:
            continue
        normalized = cleaned_tag.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return cleaned


def _compute_data_quality_score(
    *,
    salary_disclosed: bool,
    location_cleaned: str | None,
    skills: list[str],
    word_count: int,
) -> float:
    """Same four-signal, equally-weighted formula every other cleaner uses."""
    signals = [
        salary_disclosed,
        location_cleaned is not None,
        len(skills) > 0,
        word_count >= _SUBSTANTIAL_DESCRIPTION_WORD_COUNT,
    ]
    return round(sum(signals) / len(signals), 2)


def map_employment_type(raw: str | None) -> str | None:
    """Map the detail's ``JobNature`` onto ref.employment_types.code."""
    if not raw:
        return None
    mapped = _EMPLOYMENT_MAP.get(_normalize(raw))
    if mapped is None:
        logger.warning(
            "Unrecognized Bdjobs employment type {!r} -- employment_type_code "
            "left None; the raw value is preserved in raw_payload.",
            raw,
        )
    return mapped


def map_work_mode(raw: str | None) -> str | None:
    """Map the detail's ``JobWorkPlace`` onto ref.remote_work_types.code."""
    if not raw:
        return None
    mapped = _WORK_MODE_MAP.get(_normalize(raw))
    if mapped is not None:
        return mapped
    # Fall back to the shared mapper for anything not in the local table
    # (e.g. a "Remote (country)" phrasing).
    return map_remote_work_type(raw)


def map_pay_period(salary_text: str | None) -> str:
    """Read the pay period from a range like ``"Tk. 20000 - 30000 (Monthly)"``.

    Bangladesh boards quote monthly pay by convention, so an unstated period
    defaults to ``monthly``.
    """
    if salary_text:
        lowered = salary_text.lower()
        tokens = re.findall(r"\(([^)]*)\)", lowered)
        for token in [*tokens, lowered]:
            for key, value in _PAY_PERIOD_TOKENS.items():
                if key in token:
                    return value
    return "monthly"


def _positive(value: int | None) -> int | None:
    """A positive bound passes through; 0/negative means "unstated" -> None."""
    if value is None:
        return None
    return int(value) if int(value) > 0 else None


def parse_experience_years(text: str | None) -> tuple[int | None, int | None]:
    """Extract ``(min, max)`` years from a prose experience blurb.

    Recognizes ``"N to M years"``, ``"At least N years"``, ``"At most N
    years"`` and ``"N years"``; returns ``(None, None)`` when nothing
    numeric is present. A reversed pair is returned as written and swapped
    by the caller.
    """
    if not text:
        return None, None
    match = _EXP_RANGE.search(text)
    if match:
        return int(float(match.group(1))), int(float(match.group(2)))
    match = _EXP_AT_LEAST.search(text)
    if match:
        return int(float(match.group(1))), None
    match = _EXP_AT_MOST.search(text)
    if match:
        return None, int(float(match.group(1)))
    match = _EXP_PLAIN.search(text)
    if match:
        return int(float(match.group(1))), None
    return None, None


class BdjobsCleaner:
    """Cleans a batch of validated Bdjobs records into CleanedJob records."""

    def clean_job(self, raw_job: RawBdjobsJob) -> CleanedJob:
        """Clean a single validated Bdjobs job record."""
        description_parts = [
            clean_html_text(part)
            for part in (
                raw_job.description_html,
                raw_job.requirements_html,
                raw_job.education_html,
                raw_job.benefits_html,
            )
        ]
        description_clean = clean_plain_text(
            "\n\n".join(part for part in description_parts if part)
        )
        location_cleaned = clean_plain_text(raw_job.location_text) or None
        skills = _clean_tags(raw_job.skills_raw)
        word_count = len(description_clean.split()) if description_clean else 0

        salary_min = _positive(raw_job.salary_min_raw)
        salary_max = _positive(raw_job.salary_max_raw)
        # Explicit site-side withhold (ShowSalary == "0"): never disclose.
        if raw_job.salary_show_flag is False:
            salary_min = salary_max = None
        # Reversed bounds come back occasionally (site data error); swap
        # rather than drop -- the same rule the TimesJobs/Glints cleaners use.
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            logger.warning(
                "Bdjobs job {}: reversed salary range (min={}, max={}); "
                "swapping to satisfy ck_job_salaries_range.",
                raw_job.source_job_id,
                salary_min,
                salary_max,
            )
            salary_min, salary_max = salary_max, salary_min
        salary_disclosed = salary_min is not None or salary_max is not None

        exp_text = clean_html_text(raw_job.experience_text_raw)
        exp_min, exp_max = parse_experience_years(exp_text)
        if exp_min is not None and exp_max is not None and exp_min > exp_max:
            exp_min, exp_max = exp_max, exp_min

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=clean_plain_text(raw_job.job_title) or raw_job.job_title,
            company_name=clean_plain_text(raw_job.company_name) or raw_job.company_name,
            company_logo_url=raw_job.company_logo_url,
            skills=skills,
            location_cleaned=location_cleaned,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=description_clean,
            word_count=word_count,
            apply_url=raw_job.apply_url or raw_job.original_url,
            original_url=raw_job.original_url,
            posting_date=raw_job.posting_date,
            closing_date=raw_job.closing_date,
            data_quality_score=_compute_data_quality_score(
                salary_disclosed=salary_disclosed,
                location_cleaned=location_cleaned,
                skills=skills,
                word_count=word_count,
            ),
            raw_payload=raw_job.raw_payload,
            # Bangladesh board; salary is quoted in BDT and monthly by
            # convention (module docstring).
            currency_iso_code="BDT",
            pay_period=map_pay_period(raw_job.salary_text_raw),
            employment_type_code=map_employment_type(raw_job.employment_type_raw),
            remote_work_type_code=map_work_mode(raw_job.work_mode_raw),
            experience_years_min=exp_min,
            experience_years_max=exp_max,
        )

    def clean_jobs(self, raw_jobs: list[RawBdjobsJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning Bdjobs job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "Bdjobs cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
