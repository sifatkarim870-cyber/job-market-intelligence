"""Cleans validated Irantalent records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawIrantalentJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment
calls about meaning.

Four Irantalent-specific quirks handled here:

* **Salary bounds are already whole Toman** (observed 200,000,000 ..
  1,700,000,000 — monthly figures by Iranian market convention) — no
  scaling step exists here, unlike Jobvision's millions-of-Toman. The
  ≤0 bound means "no bound stated" (the Glints zero-bound rule), a
  reversed pair is swapped rather than dropped, and ``is_show_salary:
  false`` is treated as a site-side withhold (defensive: never observed
  with bounds — sampled flag-False rows carry null bounds, so the flag
  merely confirms what the nulls already say).
* **Currency is IRT**, evidenced by the platform itself: IranTalent is
  an Iran-only job board (Persian-majority ``fa``/``multi`` rows,
  Iranian employers, Iranian city names) quoting toman by convention —
  no ``تومان`` text field exists in the row the way Jobvision's
  ``titleFa`` provided, so the site-scope fact is the anchor. Pending
  the user's ``_USD_CONVERSION_RATES`` decision there is no IRT rate
  yet and normalization honestly returns NULL (non-fatal, same state
  Jobvision's IRT rows are in); whoever adds the rate must know these
  raw values are **toman** (1 toman = 10 rial).
* **Employment maps from ``employment_type.title``** ("Full Time" →
  ``full_time``, "Part Time" → ``part_time``, "Freelance" →
  ``freelance`` observed; unrecognized values fall through to None —
  raw value stays in ``raw_payload``). The site has no internship
  employment type (none in a 180-row sample) and no isInternship flag,
  so unlike Jobvision no override is needed — "Internship" would map
  via the table if it ever appears.
* **Pay period is ``monthly``**: no period field exists anywhere in
  the row, and Iranian postings quote monthly figures by convention
  (the same observed-and-documented default Jobvision's and Jobinja's
  cleaners use).

Tags merge the two labeled sources the payload offers — ``job_category``
occupation categories and the nullable brand/anonymous block's
``industry``, both **English-first** (the site ships parallel
``title``/``title_farsi`` labels and the downstream taxonomy is
English) — cleaned, lowercased, de-duplicated. ``work_type``
(``on_site``/``hybrid``) has no ``CleanedJob`` slot and stays in
``raw_payload`` only (the stance Jobvision's cleaner takes with its
``isRemote`` flag).
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.irantalent.models import RawIrantalentJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

#: ``employment_type.title`` -> ref.employment_types.code. Observed
#: live: "Full Time" (178/180), "Part Time", "Freelance". "Internship"
#: included defensively (no such type in the sample) so a future enum
#: addition maps instead of falling through.
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


def _map_employment_type(work_type_en: str | None) -> str | None:
    """Map Irantalent's employment_type.title onto ref.employment_types.code.

    Exact match after normalization; unrecognized values fall through
    to ``None`` rather than being guessed at (raw value stays in
    ``raw_payload``). No internship flag exists on this source — the
    table itself maps "Internship" should it ever appear.
    """
    if not work_type_en:
        return None
    normalized = work_type_en.strip().lower().replace("-", "_").replace(" ", "_")
    mapped = _EMPLOYMENT_MAP.get(normalized)
    if mapped is None:
        logger.warning(
            "Unrecognized Irantalent employment type {!r} -- employment_type_code "
            "left None; the raw value is preserved in raw_payload.",
            work_type_en,
        )
    return mapped


def _bound(value: int | None) -> int | None:
    """Source units (whole Toman) pass through; ≤0 means "unstated" → None."""
    if value is None:
        return None
    return int(value) if int(value) > 0 else None


class IrantalentCleaner:
    """Cleans a batch of validated Irantalent records into CleanedJob records."""

    def clean_job(self, raw_job: RawIrantalentJob) -> CleanedJob:
        """Clean a single validated Irantalent job record."""
        description_clean = clean_html_text(raw_job.description_html)
        location_cleaned = clean_plain_text(raw_job.location_text) or None
        skills = _clean_tags(raw_job.category_raws + raw_job.industry_raws)
        word_count = len(description_clean.split()) if description_clean else 0

        salary_min = _bound(raw_job.salary_min_raw)
        salary_max = _bound(raw_job.salary_max_raw)
        # Site-side withhold: flag False explicitly means "do not show"
        # (never observed with bounds — flag-False rows carry nulls —
        # so this is a defensive rule, not a sampled behavior).
        if raw_job.salary_show_flag is False:
            salary_min = salary_max = None
        # Reversed bounds come back occasionally (site data error);
        # swap rather than drop — same rule Glints' cleaner applies.
        if salary_min is not None and salary_max is not None and salary_min > salary_max:
            logger.warning(
                "Irantalent job {}: reversed salary range (min={}, max={}); "
                "swapping to satisfy ck_job_salaries_range.",
                raw_job.source_job_id,
                salary_min,
                salary_max,
            )
            salary_min, salary_max = salary_max, salary_min
        salary_disclosed = salary_min is not None or salary_max is not None

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
            apply_url=raw_job.original_url,  # no linkOut field exists on this source
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
            # Iran-only board, toman by market convention (module
            # docstring); no IRT rate in _USD_CONVERSION_RATES yet, so
            # normalization honestly returns NULL (non-fatal).
            currency_iso_code="IRT",
            # No period field exists in the payload; Iranian postings
            # quote monthly figures by convention (documented default,
            # same as Jobvision's and Jobinja's cleaners).
            pay_period="monthly",
            employment_type_code=_map_employment_type(raw_job.work_type_en),
        )

    def clean_jobs(self, raw_jobs: list[RawIrantalentJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning Irantalent job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "Irantalent cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
