"""Cleans validated Jobvision records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawJobvisionJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment
calls about meaning.

Four Jobvision-specific quirks handled here:

* **Salary is stated in millions of Toman** (``salary.min=26``/
  ``max=30`` beside ``titleFa: "26 - 30 میلیون تومان"`` / ``titleEn:
  "26 - 30 Million Tomans"`` — confirmed on every disclosed row in a
  25-job sample). The raw model keeps those source units; here they are
  scaled to whole Toman (×1,000,000). ``salary: null`` (10/25 sampled)
  means the poster withheld the figure ⇒ undisclosed; a ≤0 bound means
  "no bound stated" (the Glints zero-bound rule — storing 0 trips
  ``ck_job_salaries_range`` semantics), and a reversed pair is swapped
  rather than dropped (the site's data error, not a reason to lose the
  salary).
* **Disclosure is structural**: unlike Jobinja (where a visible
  "توافقی" can override a JSON-LD number), Jobvision's API *is* the
  disclosure — ``salary`` is either present or null, with no competing
  signal. No withholding logic is needed or invented.
* **Employment maps from ``workType.titleEn``** ("Full Time" →
  ``full_time``, "Full Time Or Part Time" → None: the ref enum has no
  hybrid code and guessing would be a lie; raw value stays in
  ``raw_payload``), with the site's own ``isInternship`` boolean
  treated as authoritative when set.
* **Currency is IRT (Iranian Toman)** — evidenced by the salary text
  (``تومان``) and anchored by ``location.country`` (``ایران``, 25/25
  observed; the site is Iran-only). Pay period is ``monthly``: Iranian
  postings quote monthly figures by convention (the same
  observed-and-documented default Jobinja's cleaner uses), and no
  period field exists anywhere in the payload.

Tags merge the five sources the payload offers — occupation
``jobCategories``, required ``software`` (Word/Excel/سپیدار/تدبیر
observed), ``languageRequirements``, company ``industries``, and the
(usually empty) ``skills`` list — cleaned, lowercased, de-duplicated.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.jobvision.models import RawJobvisionJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

#: The API states salary bounds in **millions of Toman**
#: (titleEn "26 - 30 Million Tomans" beside min=26/max=30).
_TOMAN_SCALE = 1_000_000

#: ``workType.titleEn`` -> ref.employment_types.code. Observed live:
#: "Full Time" (23/25), "Full Time Or Part Time" (2/25 — no hybrid ref
#: code exists, so it falls through to None honestly).
_EMPLOYMENT_MAP = {
    "full_time": "full_time",
    "part_time": "part_time",
    "internship": "internship",
    "contract": "contract",
    "temporary": "temporary",
    "freelance": "freelance",
    "apprenticeship": "apprenticeship",
}


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


def _map_employment_type(work_type_en: str | None, is_internship: bool) -> str | None:
    """Map Jobvision's workType onto ref.employment_types.code.

    The site's ``isInternship`` flag is authoritative when set (it
    survives any future wording of ``workType``). Otherwise exact match
    after normalization; unrecognized values fall through to ``None``
    rather than being guessed at (raw value stays in ``raw_payload``).
    """
    if is_internship:
        return "internship"
    if not work_type_en:
        return None
    normalized = work_type_en.strip().lower().replace("-", "_").replace(" ", "_")
    mapped = _EMPLOYMENT_MAP.get(normalized)
    if mapped is None:
        logger.warning(
            "Unrecognized Jobvision workType {!r} -- employment_type_code "
            "left None; the raw value is preserved in raw_payload.",
            work_type_en,
        )
    return mapped


def _bound_to_toman(value: int | None) -> int | None:
    """Millions of Toman → whole Toman; ≤0 means "unstated" → None."""
    if value is None:
        return None
    scaled = int(value) * _TOMAN_SCALE
    return scaled if scaled > 0 else None


class JobvisionCleaner:
    """Cleans a batch of validated Jobvision records into CleanedJob records."""

    def clean_job(self, raw_job: RawJobvisionJob) -> CleanedJob:
        """Clean a single validated Jobvision job record."""
        description_clean = clean_html_text(raw_job.description_html)
        location_cleaned = clean_plain_text(", ".join(raw_job.location_parts)) or None
        skills = _clean_tags(
            raw_job.category_raws
            + raw_job.software_names
            + raw_job.language_names
            + raw_job.industry_raws
            + raw_job.skills_raws
        )
        word_count = len(description_clean.split()) if description_clean else 0

        salary_min = _bound_to_toman(raw_job.salary_min_raw)
        salary_max = _bound_to_toman(raw_job.salary_max_raw)
        # Reversed bounds come back occasionally (site data error);
        # swap rather than drop — same rule Glints' cleaner applies.
        if (
            salary_min is not None
            and salary_max is not None
            and salary_min > salary_max
        ):
            logger.warning(
                "Jobvision job {}: reversed salary range (min={}, max={}); "
                "swapping to satisfy ck_job_salaries_range.",
                raw_job.source_job_id,
                salary_min,
                salary_max,
            )
            salary_min, salary_max = salary_max, salary_min
        salary_disclosed = salary_min is not None or salary_max is not None

        salary_text = raw_job.salary_title_fa or ""
        country = raw_job.country_fa or ""
        if "تومان" in salary_text:
            currency = "IRT"
        elif country in ("ایران", "Iran"):
            currency = "IRT"
        else:
            # Never observed (site is Iran-only); defensive so an
            # unexpected payload degrades to the documented fallback
            # plus a visible warning instead of a crash.
            logger.warning(
                "Jobvision job {}: no Toman evidence and country {!r}; "
                "currency falls back to USD.",
                raw_job.source_job_id,
                country,
            )
            currency = "USD"

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
            apply_url=raw_job.link_out_address or raw_job.original_url,
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
            currency_iso_code=currency,
            # No period field exists in the payload; Iranian postings
            # quote monthly figures by convention (documented default,
            # same as Jobinja's cleaner).
            pay_period="monthly",
            employment_type_code=_map_employment_type(
                raw_job.work_type_en, raw_job.is_internship
            ),
        )

    def clean_jobs(self, raw_jobs: list[RawJobvisionJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning Jobvision job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "Jobvision cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
