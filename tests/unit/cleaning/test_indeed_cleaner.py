"""Unit tests for job_market_intel.cleaning.indeed_cleaner.IndeedCleaner.

Focus areas specific to Indeed (see indeed_cleaner.py's module docstring
for the two documented differences from every other source's cleaner):
    - Only explicitly-annual salary text produces salary_min/salary_max;
      hourly/monthly/unlabeled text is left undisclosed rather than
      guessed at.
    - Sponsored/no-detail-url records fall back to a real, traceable
      original_url instead of an empty string.
"""

from __future__ import annotations

from job_market_intel.cleaning.indeed_cleaner import IndeedCleaner
from job_market_intel.scrapers.indeed.models import RawIndeedJob


def _raw_job(**overrides: object) -> RawIndeedJob:
    base = dict(
        source_job_id="abc123",
        job_title="Software Engineer",
        company_name="Acme Corp",
        query_text="software engineer",
        location_text="Austin, TX",
        search_page_number=1,
        detail_url="https://www.indeed.com/viewjob?jk=abc123",
    )
    base.update(overrides)
    return RawIndeedJob.model_validate(base)


class TestSalaryParsing:
    def test_annual_range_is_parsed(self) -> None:
        job = _raw_job(salary_text="$90,000 - $120,000 a year")
        cleaned = IndeedCleaner().clean_job(job)
        assert cleaned.salary_min == 90000
        assert cleaned.salary_max == 120000
        assert cleaned.salary_disclosed is True

    def test_single_annual_figure_sets_min_equals_max(self) -> None:
        job = _raw_job(salary_text="$75,000 a year")
        cleaned = IndeedCleaner().clean_job(job)
        assert cleaned.salary_min == 75000
        assert cleaned.salary_max == 75000

    def test_hourly_rate_is_not_stored_as_salary(self) -> None:
        job = _raw_job(salary_text="$45 - $47 an hour")
        cleaned = IndeedCleaner().clean_job(job)
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_no_salary_text_is_undisclosed(self) -> None:
        job = _raw_job(salary_text=None)
        cleaned = IndeedCleaner().clean_job(job)
        assert cleaned.salary_disclosed is False

    def test_annual_marker_case_insensitive(self) -> None:
        job = _raw_job(salary_text="$80,000 A YEAR")
        cleaned = IndeedCleaner().clean_job(job)
        assert cleaned.salary_min == 80000


class TestOriginalUrlFallback:
    def test_uses_detail_url_when_present(self) -> None:
        job = _raw_job(detail_url="https://www.indeed.com/viewjob?jk=zz")
        cleaned = IndeedCleaner().clean_job(job)
        assert cleaned.original_url == "https://www.indeed.com/viewjob?jk=zz"

    def test_falls_back_to_search_url_for_sponsored_cards(self) -> None:
        job = _raw_job(
            detail_url=None,
            is_sponsored=True,
            query_text="data analyst",
            location_text="Remote",
        )
        cleaned = IndeedCleaner().clean_job(job)
        assert cleaned.original_url.startswith("https://www.indeed.com/jobs?")
        assert "data+analyst" in cleaned.original_url
        assert cleaned.original_url  # never empty


class TestDataQualityScore:
    def test_fully_populated_record_scores_higher_than_empty_one(self) -> None:
        rich = _raw_job(
            salary_text="$100,000 a year",
            location_raw="Austin, TX",
            description_raw="word " * 30,
        )
        sparse = _raw_job(salary_text=None, location_raw=None, description_raw=None)
        cleaner = IndeedCleaner()
        rich_score = cleaner.clean_job(rich).data_quality_score
        sparse_score = cleaner.clean_job(sparse).data_quality_score
        assert rich_score > sparse_score

    def test_score_is_between_zero_and_one(self) -> None:
        cleaned = IndeedCleaner().clean_job(_raw_job())
        assert 0.0 <= cleaned.data_quality_score <= 1.0


class TestBatchCleaning:
    def test_clean_jobs_returns_same_count_for_valid_input(self) -> None:
        jobs = [_raw_job(source_job_id="a"), _raw_job(source_job_id="b")]
        cleaned = IndeedCleaner().clean_jobs(jobs)
        assert len(cleaned) == 2
