"""Unit tests for job_market_intel.cleaning.reed_cleaner.ReedCleaner.

Focused specifically on the parts of this cleaner that are genuinely new
relative to every other source's cleaner: the confirmed pay-period
mapping, the confirmed employment-type precedence rule (and its known
"permanent + part-time" gap), the GBP undisclosed-salary default, and
float-to-int salary rounding. Everything else (HTML cleaning, word count,
data quality scoring) reuses logic already covered by
``test_remoteok_cleaner.py``/``test_remotive_cleaner.py``.
"""

from __future__ import annotations

from job_market_intel.cleaning.reed_cleaner import ReedCleaner, _map_employment_type
from job_market_intel.scrapers.reed.models import RawReedJob


def _raw_job(**overrides: object) -> RawReedJob:
    defaults: dict = {
        "source_job_id": "1",
        "job_title": "AI Engineer",
        "company_name": "Acme",
        "location_raw": "London",
        "description_raw": "A description with a reasonable number of words in it to count.",
        "original_url": "https://reed.example/1",
        "apply_url": None,
        "salary_min": None,
        "salary_max": None,
        "currency_iso_code": None,
        "pay_period_raw": None,
        "full_time": None,
        "part_time": None,
        "contract_type_raw": None,
        "posting_date": None,
        "closing_date": None,
        "raw_payload": {},
    }
    defaults.update(overrides)
    return RawReedJob(**defaults)


class TestPayPeriodMapping:
    def test_per_annum_maps_to_yearly(self) -> None:
        job = _raw_job(salary_min=75000.0, salary_max=75000.0, pay_period_raw="per annum")
        cleaned = ReedCleaner().clean_job(job)
        assert cleaned.pay_period == "yearly"

    def test_per_day_maps_to_daily(self) -> None:
        # The real Step-27-style case that motivated this whole change.
        job = _raw_job(salary_min=450.0, salary_max=600.0, pay_period_raw="per day")
        cleaned = ReedCleaner().clean_job(job)
        assert cleaned.pay_period == "daily"
        assert cleaned.salary_min == 450
        assert cleaned.salary_max == 600

    def test_per_hour_maps_to_hourly(self) -> None:
        job = _raw_job(salary_min=20.0, salary_max=25.0, pay_period_raw="per hour")
        assert ReedCleaner().clean_job(job).pay_period == "hourly"

    def test_per_week_maps_to_weekly(self) -> None:
        job = _raw_job(salary_min=500.0, salary_max=600.0, pay_period_raw="per week")
        assert ReedCleaner().clean_job(job).pay_period == "weekly"

    def test_per_month_maps_to_monthly(self) -> None:
        job = _raw_job(salary_min=4000.0, salary_max=5000.0, pay_period_raw="per month")
        assert ReedCleaner().clean_job(job).pay_period == "monthly"

    def test_case_insensitive_matching(self) -> None:
        job = _raw_job(salary_min=1.0, salary_max=2.0, pay_period_raw="Per Annum")
        assert ReedCleaner().clean_job(job).pay_period == "yearly"

    def test_missing_pay_period_defaults_to_yearly_harmlessly(self) -> None:
        job = _raw_job(salary_min=None, salary_max=None, pay_period_raw=None)
        cleaned = ReedCleaner().clean_job(job)
        assert cleaned.pay_period == "yearly"
        assert cleaned.salary_disclosed is False

    def test_unrecognized_pay_period_falls_back_to_yearly(self) -> None:
        job = _raw_job(salary_min=1.0, salary_max=2.0, pay_period_raw="per fortnight")
        cleaned = ReedCleaner().clean_job(job)
        assert cleaned.pay_period == "yearly"
        # The real, unmapped value is still preserved for later inspection.
        assert cleaned.raw_payload == job.raw_payload


class TestEmploymentTypePrecedence:
    """Confirmed rule: contractType wins when contract/temporary; otherwise
    fall back to fullTime/partTime. permanent+part-time is a known,
    accepted gap (Fahim's own call)."""

    def test_contract_wins_over_full_time(self) -> None:
        assert (
            _map_employment_type(full_time=True, part_time=False, contract_type_raw="Contract")
            == "contract"
        )

    def test_temporary_wins_over_part_time(self) -> None:
        assert (
            _map_employment_type(full_time=False, part_time=True, contract_type_raw="Temporary")
            == "temporary"
        )

    def test_permanent_falls_back_to_full_time(self) -> None:
        assert (
            _map_employment_type(full_time=True, part_time=False, contract_type_raw="Permanent")
            == "full_time"
        )

    def test_permanent_falls_back_to_part_time(self) -> None:
        # The documented, accepted gap: this is really "permanent AND
        # part-time" but only "part_time" survives -- by design, not a bug.
        assert (
            _map_employment_type(full_time=False, part_time=True, contract_type_raw="Permanent")
            == "part_time"
        )

    def test_nothing_reported_returns_none(self) -> None:
        assert _map_employment_type(full_time=None, part_time=None, contract_type_raw=None) is None

    def test_unrecognized_contract_type_falls_back_to_hours(self) -> None:
        assert (
            _map_employment_type(
                full_time=True, part_time=False, contract_type_raw="Zero Hours"
            )
            == "full_time"
        )

    def test_via_clean_job_end_to_end(self) -> None:
        job = _raw_job(full_time=True, part_time=False, contract_type_raw="Contract")
        cleaned = ReedCleaner().clean_job(job)
        assert cleaned.employment_type_code == "contract"


class TestUndisclosedSalaryDefaults:
    def test_missing_currency_defaults_to_gbp(self) -> None:
        job = _raw_job(salary_min=None, salary_max=None, currency_iso_code=None)
        cleaned = ReedCleaner().clean_job(job)
        assert cleaned.currency_iso_code == "GBP"

    def test_real_currency_is_not_overridden(self) -> None:
        job = _raw_job(salary_min=1.0, salary_max=2.0, currency_iso_code="GBP")
        cleaned = ReedCleaner().clean_job(job)
        assert cleaned.currency_iso_code == "GBP"


class TestSalaryRounding:
    def test_whole_numbers_pass_through_unchanged(self) -> None:
        job = _raw_job(salary_min=75000.0, salary_max=85000.0)
        cleaned = ReedCleaner().clean_job(job)
        assert cleaned.salary_min == 75000
        assert cleaned.salary_max == 85000
        assert isinstance(cleaned.salary_min, int)

    def test_fractional_value_is_rounded_not_truncated(self) -> None:
        job = _raw_job(salary_min=450.6, salary_max=600.4)
        cleaned = ReedCleaner().clean_job(job)
        assert cleaned.salary_min == 451
        assert cleaned.salary_max == 600

    def test_none_salary_stays_none(self) -> None:
        job = _raw_job(salary_min=None, salary_max=None)
        cleaned = ReedCleaner().clean_job(job)
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None


class TestNoSkillsField:
    def test_skills_always_empty(self) -> None:
        cleaned = ReedCleaner().clean_job(_raw_job())
        assert cleaned.skills == []


class TestApplyUrlFallback:
    def test_falls_back_to_original_url_when_no_apply_url(self) -> None:
        job = _raw_job(apply_url=None, original_url="https://reed.example/1")
        cleaned = ReedCleaner().clean_job(job)
        assert cleaned.apply_url == "https://reed.example/1"

    def test_uses_apply_url_when_given(self) -> None:
        job = _raw_job(apply_url="https://employer.example/apply")
        cleaned = ReedCleaner().clean_job(job)
        assert cleaned.apply_url == "https://employer.example/apply"


class TestCleanJobsSkipsFailures:
    def test_batch_continues_past_unexpected_error(self, monkeypatch) -> None:
        cleaner = ReedCleaner()
        good_job = _raw_job(source_job_id="1")
        bad_job = _raw_job(source_job_id="2")

        original_clean_job = cleaner.clean_job

        def flaky_clean_job(raw_job: RawReedJob):
            if raw_job.source_job_id == "2":
                raise RuntimeError("boom")
            return original_clean_job(raw_job)

        monkeypatch.setattr(cleaner, "clean_job", flaky_clean_job)
        result = cleaner.clean_jobs([good_job, bad_job])

        assert len(result) == 1
        assert result[0].source_job_id == "1"
