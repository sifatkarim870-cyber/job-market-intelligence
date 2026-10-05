"""Cleans validated 51job records into standardized, storage-ready records.

Same boundary as the other cleaners: ``RawJob51Job`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment calls
about meaning.

Two 51job-specific calibrations live here (both documented at their
call sites below): the CNY/monthly salary context — the first source
since Reed that actually *carries* salary data — and a CJK-aware word
count, because Chinese descriptions have no inter-word spaces and the
shared ``len(text.split())`` formula would report a 3,000-character job
description as a handful of "words", systematically mis-scoring every
job from this source on the word-count quality signal.
"""

from __future__ import annotations

import re

from loguru import logger

from job_market_intel.scrapers.job51.models import RawJob51Job

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

# 51job's termStr, observed over 300 general-feed items (2026-10-05):
# "全职" (299) and "兼职" (1). Anything else (e.g. a future "实习"
# internship posting) maps if listed here and falls through to None with
# a warning otherwise — the real string always stays in raw_payload.
_EMPLOYMENT_MAP = {
    "全职": "full_time",
    "兼职": "part_time",
    "实习": "internship",
}

# CJK ideographs (incl. extension A and compatibility blocks): characters
# that belong to writing systems without inter-word spaces.
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _map_employment_type(employment_type_raw: str | None) -> str | None:
    """Map 51job's ``termStr`` to one reference code; unknown → None."""
    if not employment_type_raw:
        return None
    text = employment_type_raw.strip()
    mapped = _EMPLOYMENT_MAP.get(text)
    if mapped:
        return mapped
    for key, value in _EMPLOYMENT_MAP.items():
        if key in text:
            return value
    logger.warning(
        "Unrecognized 51job termStr {!r} -- employment_type_code left None; "
        "the real value is still preserved in raw_payload.",
        employment_type_raw,
    )
    return None


def _detect_pay_period(salary_text: str | None) -> str:
    """Cadence for this job's salary bounds, read off the display string.

    51job's ``provideSalaryString`` observed forms are monthly by
    construction (``"4-5千"``, ``"1.2-1.8万"``, ``"5-6千·13薪"`` — the
    ``·13薪`` variant still means monthly pay across 13 months), so
    monthly is the default. A daily/hourly posting would spell its unit
    out (``"…元/天"``, ``"…元/时"``); those markers switch the cadence so
    the normalization layer multiplies by the right annualizer. Unmatched
    exotic forms stay monthly — the display string itself is always
    preserved in ``raw_payload`` for audit.
    """
    if salary_text and ("/天" in salary_text or "元/天" in salary_text):
        return "daily"
    if salary_text and ("/时" in salary_text or "元/时" in salary_text):
        return "hourly"
    return "monthly"


def _count_words(description: str) -> int:
    """Word count that doesn't collapse on Chinese text.

    The shared formula (``len(text.split())``) counts space-delimited
    tokens — correct for every script 51job's peers use (English, French,
    Armenian, Arabic all put spaces between words) but wrong for Chinese,
    where a full job description is often a single "token". Here each
    CJK character counts as one word (Microsoft Word's convention for
    Chinese), plus the space-delimited tokens of the *non*-CJK remainder
    (Latin tool names, numbers, punctuation runs). Result: sane magnitudes
    for this source (a 3,000-character description scores ~3,000, not
    ~10), so both the quality signal and ``core.job_descriptions
    .word_count`` stay meaningful. Other sources are untouched — their
    scripts already tokenize correctly.
    """
    cjk_characters = len(_CJK_RE.findall(description))
    without_cjk = _CJK_RE.sub(" ", description)
    return cjk_characters + len(without_cjk.split())


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


class Job51Cleaner:
    """Cleans a batch of validated 51job records into CleanedJob records."""

    def clean_job(self, raw_job: RawJob51Job) -> CleanedJob:
        """Clean a single validated 51job job record."""
        description_clean = clean_html_text(raw_job.description_raw)
        location_cleaned = clean_plain_text(raw_job.location_raw)
        # jobTags on 51job are welfare/degree/experience labels
        # ("员工旅游", "大专", "1-3年"), not skills — putting them in
        # skills would poison the vocabulary, so skills start empty and
        # the separate skill-extraction batch fills bridge.job_skills
        # from the description (same path Job.am's jobs take).
        skills: list[str] = []
        word_count = _count_words(description_clean) if description_clean else 0

        # 51job is the first source since Reed whose payload actually
        # carries salary (300/300 items during scoping): bounds arrive
        # in yuan already normalized ("12000" for "1.2-1.8万"), cadence
        # from _detect_pay_period. Absence is possible and honest →
        # salary_disclosed False, no rows in salary.job_salaries.
        salary_min = raw_job.salary_min
        salary_max = raw_job.salary_max
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
            currency_iso_code="CNY",
            pay_period=_detect_pay_period(raw_job.salary_text),
            employment_type_code=_map_employment_type(raw_job.employment_type_raw),
        )

    def clean_jobs(self, raw_jobs: list[RawJob51Job]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning 51job job {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "51job cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
