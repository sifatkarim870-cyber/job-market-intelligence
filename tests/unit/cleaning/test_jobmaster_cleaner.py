"""Unit tests for job_market_intel.cleaning.jobmaster_cleaner.

Raw jobs come from the ``make_raw_jobmaster_job`` conftest factory
(live row 9884960-ish snapshot). Validation of thresholds is the
validator's, so here we pin the cleaner's mapping contract in
isolation.
"""

from __future__ import annotations

from collections.abc import Callable

from job_market_intel.cleaning.jobmaster_cleaner import JobmasterCleaner
from job_market_intel.scrapers.jobmaster.models import RawJobmasterJob


def _clean(raw: RawJobmasterJob):
    return JobmasterCleaner().clean_job(raw)


class TestEmploymentTypeMapping:
    def test_full_time_hebrew_maps(
        self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]
    ) -> None:
        cleaned = _clean(make_raw_jobmaster_job(work_type_label="משרה מלאה"))
        assert cleaned.employment_type_code == "full_time"

    def test_part_time_hebrew_maps(
        self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]
    ) -> None:
        cleaned = _clean(make_raw_jobmaster_job(work_type_label="משרה חלקית"))
        assert cleaned.employment_type_code == "part_time"

    def test_unknown_label_becomes_none(
        self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]
    ) -> None:
        # "משמרות" (shifts) has no ref.employment_types code — honest None
        # rather than a wrong guess.
        cleaned = _clean(make_raw_jobmaster_job(work_type_label="משמרות"))
        assert cleaned.employment_type_code is None

    def test_missing_label_becomes_none(
        self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]
    ) -> None:
        cleaned = _clean(make_raw_jobmaster_job(work_type_label=None))
        assert cleaned.employment_type_code is None


class TestSalaryParsing:
    def test_undisclosed_marker_withholds(
        self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]
    ) -> None:
        cleaned = _clean(make_raw_jobmaster_job(salary_text="לא צוין שכר"))
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_monthly_range(self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]) -> None:
        cleaned = _clean(make_raw_jobmaster_job(salary_text="₪12,000 - ₪18,000 לחודש"))
        assert cleaned.salary_min == 12_000
        assert cleaned.salary_max == 18_000
        assert cleaned.salary_disclosed is True
        assert cleaned.pay_period == "monthly"

    def test_single_amount(self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]) -> None:
        cleaned = _clean(make_raw_jobmaster_job(salary_text="₪15,000 לחודש"))
        assert cleaned.salary_min == 15_000
        assert cleaned.salary_max == 15_000

    def test_unknown_period_falls_back_to_monthly(
        self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]
    ) -> None:
        # CleanedJob.pay_period is non-optional; the site-wide
        # convention (like IranTalent's) is monthly ₪ postings.
        cleaned = _clean(make_raw_jobmaster_job(salary_text="₪10,000"))
        assert cleaned.pay_period == "monthly"

    def test_currency_is_ils(self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]) -> None:
        assert _clean(make_raw_jobmaster_job()).currency_iso_code == "ILS"


class TestTextCleaning:
    def test_description_html_is_stripped(
        self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]
    ) -> None:
        cleaned = _clean(
            make_raw_jobmaster_job(description_html="<p>בדיקות תפקודיות <b>מלאות</b></p>")
        )
        assert "בדיקות תפקודיות" in cleaned.description_clean
        assert "<" not in cleaned.description_clean
        assert cleaned.word_count >= 2

    def test_tags_are_normalized_and_deduplicated(
        self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]
    ) -> None:
        cleaned = _clean(make_raw_jobmaster_job(category_raws=["QA", " QA ", "מחשבים ותוכנה"]))
        assert cleaned.skills == ["qa", "מחשבים ותוכנה"]

    def test_quality_score_is_bounded(
        self, make_raw_jobmaster_job: Callable[..., RawJobmasterJob]
    ) -> None:
        score = _clean(make_raw_jobmaster_job()).data_quality_score
        assert 0.0 <= score <= 1.0
