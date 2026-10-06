"""Cleans validated Glints records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawGlintsJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment
calls about meaning.

Three Glints-specific quirks handled here:

* **Descriptions are Draft.js JSON**, not HTML: ``descriptionJsonString``
  is ``{"blocks": [{"text": …}, …], "entityMap": {}}``. The block texts
  are joined into plain text (falls back to HTML cleaning if a payload
  ever arrives as markup instead — degradation, not a crash). The text
  is in the posting's source language (Indonesian/Vietnamese/English);
  the translation layer owns making it English downstream.
* **Employment mapping uses the ``type`` enum** (``FULL_TIME`` →
  ``full_time``, ``PART_TIME`` → ``part_time``, ``INTERNSHIP`` →
  ``internship``, …). Unknown values fall through to ``None`` — honest
  absence rather than a guess; the raw value stays in ``raw_payload``.
* **Salary disclosure follows ``shouldShowSalary``**: observed pairing
  is amounts + ``shouldShowSalary: true`` for disclosed rows; an
  explicit ``false`` withholds the figure even if amounts were present.
  Currency comes from the salary record's ``CurrencyCode`` (IDR/VND/
  SGD/MYR observed), falling back to the job's country default so the
  required ``currency_iso_code`` is always the market's real currency;
  pay period maps Glints' ``salaryMode`` (MONTH observed → ``monthly``),
  defaulting to ``monthly`` because every observed SEA posting quotes
  monthly figures — the same "observed, documented default" reasoning
  HR.ge's cleaner uses for GEL/monthly.
"""

from __future__ import annotations

import json
import re

from loguru import logger

from job_market_intel.scrapers.glints.models import RawGlintsJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

#: Glints' ``type`` enum -> ref.employment_types.code. Observed live:
#: FULL_TIME; the others are Glints' documented posting types.
_EMPLOYMENT_MAP = {
    "full_time": "full_time",
    "part_time": "part_time",
    "internship": "internship",
    "contract": "contract",
    "temporary": "temporary",
    "freelance": "freelance",
    "apprenticeship": "apprenticeship",
}

#: Glints' ``salaryMode`` -> CleanedJob.pay_period.
_PAY_PERIOD_MAP = {
    "MONTH": "monthly",
    "YEAR": "annually",
    "WEEK": "weekly",
    "DAY": "daily",
    "HOUR": "hourly",
}

#: Country -> default currency, used when the salary record carries no
#: ``CurrencyCode`` (sourced-job fallback) so ``currency_iso_code``
#: (required) is still the market's real currency rather than a guess.
_COUNTRY_CURRENCY_MAP = {
    "ID": "IDR",
    "VN": "VND",
    "SG": "SGD",
    "MY": "MYR",
}

_URL_COUNTRY_RE = re.compile(r"^https?://[^/]+/([a-z]{2})/")


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


def _draftjs_to_text(raw: str | None) -> str | None:
    """Turn ``descriptionJsonString`` (Draft.js JSON) into plain text.

    Falls back to HTML cleaning for a non-JSON payload so a shape change
    degrades to "worse text" instead of "no description".
    """
    if not raw:
        return None
    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            document = json.loads(stripped)
        except ValueError:
            document = None
        if isinstance(document, dict):
            blocks = document.get("blocks")
            if isinstance(blocks, list):
                parts = [
                    str(block.get("text", ""))
                    for block in blocks
                    if isinstance(block, dict) and block.get("text")
                ]
                joined = " ".join(parts).strip()
                if joined:
                    return clean_plain_text(joined)
                return None  # empty document: honest absence
    return clean_html_text(raw)


def _map_employment_type(contract_type_raw: str | None) -> str | None:
    """Map Glints' ``type`` enum onto ref.employment_types.code.

    Exact match after lowercasing; unrecognized values fall through to
    ``None`` rather than being guessed at (raw value stays in
    ``raw_payload``).
    """
    if not contract_type_raw:
        return None
    normalized = contract_type_raw.strip().lower().replace("-", "_").replace(" ", "_")
    mapped = _EMPLOYMENT_MAP.get(normalized)
    if mapped is None:
        logger.warning(
            "Unrecognized Glints job type {!r} -- employment_type_code left "
            "None; the raw value is preserved in raw_payload.",
            contract_type_raw,
        )
    return mapped


class GlintsCleaner:
    """Cleans a batch of validated Glints records into CleanedJob records."""

    def clean_job(self, raw_job: RawGlintsJob) -> CleanedJob:
        """Clean a single validated Glints job record."""
        description_clean = _draftjs_to_text(raw_job.description_raw)
        location_cleaned = clean_plain_text(raw_job.location_raw)
        skills = _clean_tags(raw_job.tags)
        word_count = len(description_clean.split()) if description_clean else 0

        if raw_job.should_show_salary is False:
            salary_min, salary_max = None, None
        else:
            salary_min, salary_max = raw_job.salary_from_raw, raw_job.salary_to_raw
        salary_disclosed = salary_min is not None or salary_max is not None

        country = (raw_job.country_code or "").upper()
        if country not in _COUNTRY_CURRENCY_MAP:
            # Sourced fallbacks omit CountryCode — the canonical URL
            # always carries the country segment (…/{cc}/opportunities/…).
            match = _URL_COUNTRY_RE.match(raw_job.original_url)
            country = match.group(1).upper() if match else ""
        currency = (
            (raw_job.salary_currency or "").upper()
            or _COUNTRY_CURRENCY_MAP.get(country)
            or "USD"
        )

        pay_period = _PAY_PERIOD_MAP.get(
            (raw_job.salary_mode or "").strip().upper(), "monthly"
        )

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=clean_plain_text(raw_job.job_title) or raw_job.job_title,
            company_name=clean_plain_text(raw_job.company_name) or raw_job.company_name,
            company_logo_url=None,  # no stable CDN base observed; raw logo stays in raw_payload
            skills=skills,
            location_cleaned=location_cleaned,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=description_clean,
            word_count=word_count,
            apply_url=raw_job.external_apply_url or raw_job.original_url,
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
            employment_type_code=_map_employment_type(raw_job.contract_type_raw),
        )

    def clean_jobs(self, raw_jobs: list[RawGlintsJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning Glints job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "Glints cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
