"""Cleans validated BongThom records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawBongthomJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment calls
about meaning.

BongThom-specific quirks handled here:

* **Description is several content blobs.** The structured embed carries an
  HTML ``description`` per position plus separate prose arrays (duties,
  benefits, qualifications, experience bullet text); all are folded into one
  cleaned description, since each is job content with no separate
  ``CleanedJob`` slot.
* **Salary is a ``$`` string.** Disclosed rows read ``$<min> - $<max>`` or a
  single ``$<value>``; the rest say "Negotiable", "Based on Experience",
  "N/A", "Other Benefits" or a combination. The cleaner reads the dollar
  figures when present, keeps a single figure as the lower bound and leaves
  the upper bound genuinely unstated, and treats everything without a figure
  as undisclosed. Currency is ``USD`` (Cambodia's dollarised economy) and
  pay is quoted monthly.
* **Schedule is prose.** "Full-time", "Part-time" or "Short-term"; the
  recognized single labels are mapped onto ``ref.employment_types``. A
  combined label ("Full-time, Part-time") names two engagement types at
  once, so it is deliberately left unmapped -- the raw value stays in
  ``raw_payload`` and a warning is logged. Same rule ``blmis_bt`` applies
  to that board's "Casual/Freelance".
* **Work location doubles as a remote signal.** A location list that names
  "Working from home" or "online" marks the posting ``remote_country``
  (remote within the board's own country, Cambodia); no signal here narrows
  it further.
* **Experience is numeric.** ``experiences[].years`` is whole years; the
  cleaner keeps the minimum across a posting's positions and nothing else.
* **Skills are requirement strings.** ``skill_knowledges[].skill`` values
  (language, soft and hard alike) are cleaned, lowercased and de-duplicated.
"""

from __future__ import annotations

import re

from loguru import logger

from job_market_intel.scrapers.bongthom_com.models import RawBongthomJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

#: ``Schedule:`` label -> ref.employment_types.code. A combined label is not
#: in the table and is left unmapped rather than guessed.
_EMPLOYMENT_MAP = {
    "full time": "full_time",
    "fulltime": "full_time",
    "permanent": "full_time",
    "part time": "part_time",
    "parttime": "part_time",
    "short term": "temporary",
    "shortterm": "temporary",
    "temporary": "temporary",
    "contract": "contract",
    "freelance": "freelance",
    "internship": "internship",
    "intern": "internship",
    "apprenticeship": "apprenticeship",
}

#: ``$1,200 - $1,500`` / ``$1,200 to $1,500`` (a range), tried before the
#: single-value pattern.
_SALARY_RANGE = re.compile(
    r"\$\s*([\d,]+(?:\.\d+)?)\s*(?:-|to)\s*\$?\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)

#: A lone ``$1,200``.
_SALARY_SINGLE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")

#: A location list naming one of these is a home-working post.
_REMOTE_MARKERS = ("working from home", "work from home", "online")


def _normalize(value: str) -> str:
    """Lowercase, hyphens/slashes/underscores -> spaces, collapse runs."""
    lowered = value.strip().lower().replace("-", " ").replace("/", " ").replace("_", " ")
    return re.sub(r"\s+", " ", lowered).strip()


def _clean_skills(raw_skills: list[str]) -> list[str]:
    """Clean, lowercase, and de-duplicate raw skill strings, first-seen order."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw_skill in raw_skills:
        clean_skill = clean_plain_text(raw_skill)
        if not clean_skill:
            continue
        normalized = clean_skill.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return cleaned


def _to_number(value: str) -> float:
    """Parse a ``$`` figure body (commas allowed) into a float."""
    return float(value.replace(",", ""))


def parse_salary(text: str | None) -> tuple[float | None, float | None]:
    """Parse a BongThom ``Salary:`` value into ``(min, max)``.

    Reads a ``$min - $max`` range, then a lone ``$value`` as the lower
    bound; anything without a dollar figure ("Negotiable", "Based on
    Experience", "N/A", "Other Benefits") is undisclosed.
    """
    if not text:
        return None, None
    match = _SALARY_RANGE.search(text)
    if match:
        return _to_number(match.group(1)), _to_number(match.group(2))
    match = _SALARY_SINGLE.search(text)
    if match:
        return _to_number(match.group(1)), None
    return None, None


def map_employment_type(raw: str | None) -> str | None:
    """Map the rendered ``Schedule:`` value onto ref.employment_types.code."""
    if not raw:
        return None
    mapped = _EMPLOYMENT_MAP.get(_normalize(raw))
    if mapped is None:
        logger.warning(
            "Unrecognized BongThom schedule {!r} -- employment_type_code left "
            "None; the raw value is preserved in raw_payload.",
            raw,
        )
    return mapped


def map_remote_work_type(location_text: str | None) -> str | None:
    """``remote_country`` for a home-working location list, else ``None``."""
    if not location_text:
        return None
    lowered = location_text.lower()
    if any(marker in lowered for marker in _REMOTE_MARKERS):
        return "remote_country"
    return None


def _compose_description(raw_job: RawBongthomJob) -> str | None:
    """Fold the board's several content blobs into one cleaned description."""
    parts = [clean_html_text(part) for part in raw_job.description_htmls]
    parts += [clean_plain_text(part) for part in raw_job.duty_texts]
    parts += [clean_plain_text(part) for part in raw_job.benefit_texts]
    parts += [clean_plain_text(part) for part in raw_job.qualification_texts]
    parts += [clean_plain_text(part) for part in raw_job.experience_texts]
    joined = "\n\n".join(part for part in parts if part)
    return clean_plain_text(joined) or None


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


class BongthomCleaner:
    """Cleans a batch of validated BongThom records into CleanedJob records."""

    def clean_job(self, raw_job: RawBongthomJob) -> CleanedJob:
        """Clean a single validated BongThom job record."""
        description_clean = _compose_description(raw_job)
        location_cleaned = clean_plain_text(raw_job.location_text) or None
        skills = _clean_skills(raw_job.skills_raw)
        word_count = len(description_clean.split()) if description_clean else 0

        salary_min, salary_max = parse_salary(raw_job.salary_text_raw)
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            logger.warning(
                "BongThom job {}: reversed salary range (min={}, max={}); "
                "swapping to satisfy ck_job_salaries_range.",
                raw_job.source_job_id,
                salary_min,
                salary_max,
            )
            salary_min, salary_max = salary_max, salary_min
        salary_disclosed = salary_min is not None or salary_max is not None

        experience_years_min = min(raw_job.experience_years_raw, default=None)

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
            apply_url=raw_job.original_url,
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
            # Cambodia quotes a monthly salary in US dollars (module docstring).
            currency_iso_code="USD",
            pay_period="monthly",
            employment_type_code=map_employment_type(raw_job.employment_type_raw),
            remote_work_type_code=map_remote_work_type(raw_job.location_text),
            experience_years_min=experience_years_min,
        )

    def clean_jobs(self, raw_jobs: list[RawBongthomJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning BongThom job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "BongThom cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
