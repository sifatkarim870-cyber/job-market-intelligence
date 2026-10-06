"""Cleans validated Jobinja records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawJobinjaJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment
calls about meaning.

Four Jobinja-specific quirks handled here:

* **The ``حقوق`` HTML section is the salary disclosure truth**, not the
  JSON-LD. Negotiable postings ("توافقی") still carry a numeric
  ``baseSalary`` in their structured data (observed live: value 5000000
  beside "توافقی"), so a negotiable section withholds the figure even
  though JSON-LD would supply one. When the section states a number
  ("از ۴۵,۰۰۰,۰۰۰ تومان" = *from* 45,000,000 toman), Persian/Arabic
  numerals and thousand separators are normalized and the "از" form
  becomes ``salary_min`` only (at-least semantics — honest absence of a
  ceiling); "از X تا Y" becomes a real range; a bare figure likewise
  sets the minimum. Only when the section is missing or unparseable
  does the JSON-LD value fall back in — and ≤ 0 everywhere means
  "unstated" (the same 0-bound rule Glints' cleaner applies after its
  live-observed ``maxAmount: 0`` quirk).
* **Currency is IRT** (Iranian Toman — what the site quotes even though
  IRR is the ISO tender currency; seeded into ``ref.currencies``),
  falling back to the job's country default so the required
  ``currency_iso_code`` is always the market's real currency.
* **Pay period maps schema.org ``unitText``** (``MONTH`` observed →
  ``monthly``; ``HOUR``/``DAY``/``WEEK``/``YEAR`` are the rest of the
  enum), defaulting to ``monthly`` because every observed Iranian
  posting quotes monthly toman — the same "observed, documented
  default" reasoning HR.ge's cleaner uses for GEL/monthly.
* **Employment maps schema.org ``employmentType``** (``FULL_TIME`` →
  ``full_time``, ``INTERN`` → ``internship``, ``CONTRACTOR`` →
  ``contract``); ``VOLUNTEER``/``PER_DIEM``/``OTHER`` fall through to
  ``None`` — honest absence rather than a guess; the raw value stays in
  ``raw_payload``.

Descriptions are HTML from the JSON-LD (RTL lists) and are in the
posting's source language (Persian); the translation layer owns making
them English downstream.
"""

from __future__ import annotations

import re

from loguru import logger

from job_market_intel.scrapers.jobinja.models import RawJobinjaJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

#: Jobinja's ``employmentType`` (schema.org) -> ref.employment_types.code.
#: Observed live: FULL_TIME; the others are the schema.org enum values
#: a posting could carry. VOLUNTEER / PER_DIEM / OTHER have no
#: ref.employment_types counterpart and are deliberately absent — they
#: map to None rather than being bent onto a wrong-but-close code.
_EMPLOYMENT_MAP = {
    "full_time": "full_time",
    "part_time": "part_time",
    "intern": "internship",
    "temporary": "temporary",
    "contractor": "contract",
    "freelance": "freelance",
}

#: schema.org ``unitText`` -> CleanedJob.pay_period. The targets are the
#: canonical ``ck_job_salaries_pay_period`` enum
#: ('hourly','daily','weekly','monthly','yearly') — note ``yearly``,
#: not "annually" (the mistake that failed Glints' first CI run).
_PAY_PERIOD_MAP = {
    "HOUR": "hourly",
    "H": "hourly",
    "DAY": "daily",
    "D": "daily",
    "WEEK": "weekly",
    "W": "weekly",
    "MONTH": "monthly",
    "MO": "monthly",
    "YEAR": "yearly",
    "YR": "yearly",
    "ANNUAL": "yearly",
}

#: Country -> default currency when the JSON-LD salary record carries no
#: ``currency`` (observed always IRT when salary is present) so the
#: required ``currency_iso_code`` is still the market's real currency.
_COUNTRY_CURRENCY_MAP = {
    "IR": "IRT",
}

#: Persian (۰-۹) and Arabic-Indic (٠-٩) digits → ASCII, for the
#: Persian-numeral salary text ("از ۴۵,۰۰۰,۰۰۰ تومان").
_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)

#: A run of digits with optional thousand separators ("45,000,000").
_NUMBER_RE = re.compile(r"\d[\d,]*")

#: Persian magnitude words that scale the figure they accompany
#: ("از ۴۵ میلیون تومان" = 45 million toman). Checked longest-first:
#: میلیارد (billion) before میلیون (million) before هزار (thousand).
_MAGNITUDES = (
    ("میلیارد", 1_000_000_000),
    ("میلیون", 1_000_000),
    ("هزار", 1_000),
)

#: "توافقی" — negotiable. Presence in the salary section means the
#: employer declined to state a figure; JSON-LD numbers beside it are
#: SEO sugar, not disclosure.
_NEGOTIABLE_MARK = "توافقی"


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


def _parse_salary_text(text: str) -> tuple[int | None, int | None]:
    """Persian salary text → ``(min, max)``.

    Handles the observed shapes: "از ۴۵,۰۰۰,۰۰۰ تومان" (from-N →
    ``(N, None)``), "از X تا Y" (range), a bare figure, and magnitude
    words ("۴۵ میلیون" → 45,000,000). Returns ``(None, None)`` when no
    positive number can be extracted — honest absence, not a guess.
    """
    translated = text.translate(_DIGIT_TRANSLATION)
    scale = 1
    for marker, factor in _MAGNITUDES:
        if marker in translated:
            scale = factor
            break
    numbers = [
        int(match.replace(",", "")) * scale for match in _NUMBER_RE.findall(translated)
    ]
    numbers = [n for n in numbers if n > 0]
    if len(numbers) >= 2:
        low, high = min(numbers), max(numbers)
        return low, high
    if numbers:
        # One figure: the observed copy is "از N" (at-least), and a
        # bare figure without a ceiling is the honest representation
        # either way — salary_max stays NULL.
        return numbers[0], None
    return None, None


def _map_employment_type(employment_raw: str | None) -> str | None:
    """Map Jobinja's ``employmentType`` enum onto ref.employment_types.code.

    Exact match after lowercasing; unrecognized values fall through to
    ``None`` rather than being guessed at (raw value stays in
    ``raw_payload``).
    """
    if not employment_raw:
        return None
    normalized = employment_raw.strip().lower().replace("-", "_").replace(" ", "_")
    mapped = _EMPLOYMENT_MAP.get(normalized)
    if mapped is None:
        logger.warning(
            "Unrecognized Jobinja employmentType {!r} -- employment_type_code "
            "left None; the raw value is preserved in raw_payload.",
            employment_raw,
        )
    return mapped


class JobinjaCleaner:
    """Cleans a batch of validated Jobinja records into CleanedJob records."""

    def clean_job(self, raw_job: RawJobinjaJob) -> CleanedJob:
        """Clean a single validated Jobinja job record."""
        description_clean = clean_html_text(raw_job.description_html)
        skills = _clean_tags(raw_job.skills_spans + raw_job.category_spans)
        word_count = len(description_clean.split()) if description_clean else 0

        salary_min, salary_max = self._resolve_salary(raw_job)
        salary_disclosed = salary_min is not None or salary_max is not None

        location_cleaned = clean_plain_text(", ".join(raw_job.location_spans)) or None

        country = (raw_job.country_code or "").upper()
        if raw_job.salary_currency:
            currency = raw_job.salary_currency.strip().upper()
        elif country in _COUNTRY_CURRENCY_MAP:
            currency = _COUNTRY_CURRENCY_MAP[country]
        else:
            logger.warning(
                "Jobinja job {}: no salary currency and country {!r} has no "
                "default; falling back to USD.",
                raw_job.source_job_id,
                raw_job.country_code,
            )
            currency = "USD"

        unit = (raw_job.salary_unit or "").strip().upper()
        pay_period = _PAY_PERIOD_MAP.get(unit, "monthly")

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=raw_job.job_title,
            company_name=raw_job.company_name,
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
            currency_iso_code=currency,
            pay_period=pay_period,
            employment_type_code=_map_employment_type(raw_job.employment_type_raw),
        )

    @staticmethod
    def _resolve_salary(raw_job: RawJobinjaJob) -> tuple[int | None, int | None]:
        """The visible disclosure wins; JSON-LD is the fallback figure.

        Order (documented in the module docstring): negotiate mark
        withholds → parsed section text → JSON-LD ``baseSalary.value`` →
        unstated. Every ≤ 0 figure collapses to "unstated".
        """
        section_text = " ".join(raw_job.salary_text_spans).strip()
        if section_text:
            if _NEGOTIABLE_MARK in section_text:
                return None, None
            salary_min, salary_max = _parse_salary_text(section_text)
            if salary_min is not None:
                return salary_min, salary_max

        value = raw_job.base_salary_value
        if value is not None and value > 0:
            return value, None
        return None, None

    def clean_jobs(self, raw_jobs: list[RawJobinjaJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning Jobinja job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "Jobinja cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
