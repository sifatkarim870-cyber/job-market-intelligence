"""Unit tests for job_market_intel.cleaning.jobinja_cleaner.

Pins the disclosure decisions documented in the cleaner's docstring —
the ones that decide whether a number ever reaches ``core.jobs``:

1. The visible ``حقوق`` section wins over JSON-LD: "توافقی" (negotiable)
   withholds the figure even though structured data carries one
   (observed live 2026-10-07: value 5000000 beside توافقی — 4 of the
   first 10 jobs).
2. "از N" (from-N) sets ``salary_min`` only; ranges set both; Persian
   numerals/separators/magnitude words normalize to integers.
3. JSON-LD is the fallback figure only when the section is absent or
   unparseable; ≤ 0 means "unstated".
4. Currency/pay-period/employment map onto the real ref enums
   (yearly-not-annually, IRT, honest None for unmapped employment).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from job_market_intel.cleaning.jobinja_cleaner import JobinjaCleaner
from job_market_intel.scrapers.jobinja.models import RawJobinjaJob

URL = "https://jobinja.ir/companies/acme/jobs/aaaa/x"


def _raw(**overrides) -> RawJobinjaJob:
    defaults = {
        "source_job_id": "1118910",
        "job_title": "کارشناس فروش بین المللی",
        "company_name": "Acme",
        "original_url": URL,
        "description_html": "<div>توسعه نرم‌افزار و فروش بین‌المللی است.</div>",
        "posting_date": datetime(2026, 10, 6, tzinfo=UTC),
        "employment_type_raw": "FULL_TIME",
        "base_salary_value": 45000000,
        "salary_currency": "IRT",
        "salary_unit": "MONTH",
        "location_spans": ["تهران ، تهران"],
        "salary_text_spans": ["از ۴۵,۰۰۰,۰۰۰ تومان"],
        "skills_spans": ["فروش B2B"],
        "category_spans": ["فروش و بازاریابی"],
        "country_code": "IR",
        "raw_payload": {"ld": {}, "sections": {}},
    }
    defaults.update(overrides)
    return RawJobinjaJob(**defaults)


class TestSalaryDisclosure:
    def test_from_n_sets_minimum_only(self) -> None:
        cleaned = JobinjaCleaner().clean_job(_raw())
        assert cleaned.salary_min == 45000000
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is True

    def test_negotiate_withholds_despite_json_ld_value(self) -> None:
        # The live-observed trap: structured data says 5,000,000 while
        # the poster wrote توافقی (negotiable) — the visible text wins.
        cleaned = JobinjaCleaner().clean_job(
            _raw(salary_text_spans=["توافقی"], base_salary_value=5000000)
        )
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_negotiate_wins_over_zero_and_absent_value_too(self) -> None:
        cleaned = JobinjaCleaner().clean_job(
            _raw(salary_text_spans=["توافقی"], base_salary_value=0)
        )
        assert cleaned.salary_disclosed is False

    def test_range_text_sets_both_bounds(self) -> None:
        cleaned = JobinjaCleaner().clean_job(
            _raw(
                salary_text_spans=["از ۵۰,۰۰۰,۰۰۰ تا ۷۰,۰۰۰,۰۰۰ تومان"],
                base_salary_value=None,
            )
        )
        assert cleaned.salary_min == 50000000
        assert cleaned.salary_max == 70000000

    def test_persian_magnitude_word_scales(self) -> None:
        # "از ۴۵ میلیون تومان" = from 45,000,000 toman.
        cleaned = JobinjaCleaner().clean_job(
            _raw(salary_text_spans=["از ۴۵ میلیون تومان"], base_salary_value=None)
        )
        assert cleaned.salary_min == 45_000_000
        assert cleaned.salary_max is None

    def test_section_missing_falls_back_to_json_ld(self) -> None:
        cleaned = JobinjaCleaner().clean_job(
            _raw(salary_text_spans=[], base_salary_value=40000000)
        )
        assert cleaned.salary_min == 40000000
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is True

    def test_section_unparseable_falls_back_to_json_ld(self) -> None:
        cleaned = JobinjaCleaner().clean_job(
            _raw(salary_text_spans=["مورد بحث قرار می‌گیرد"], base_salary_value=30000000)
        )
        assert cleaned.salary_min == 30000000

    @pytest.mark.parametrize("value", [0, -1])
    def test_nonpositive_json_ld_means_unstated(self, value: int) -> None:
        cleaned = JobinjaCleaner().clean_job(_raw(salary_text_spans=[], base_salary_value=value))
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_no_section_no_value_means_unstated(self) -> None:
        cleaned = JobinjaCleaner().clean_job(_raw(salary_text_spans=[], base_salary_value=None))
        assert cleaned.salary_disclosed is False
        # CleanedJob.pay_period is required even when undisclosed.
        assert cleaned.pay_period == "monthly"

    def test_irregular_digits_and_separators_normalize(self) -> None:
        # Arabic-Indic digits (٠-٩) and stray spacing must still parse.
        cleaned = JobinjaCleaner().clean_job(
            _raw(salary_text_spans=["از ٤٥,٠٠٠,٠٠٠ تومان"], base_salary_value=None)
        )
        assert cleaned.salary_min == 45_000_000


class TestCurrencyAndPeriod:
    @pytest.mark.parametrize(
        ("unit", "period"),
        [
            ("MONTH", "monthly"),
            ("YEAR", "yearly"),
            ("HOUR", "hourly"),
            ("DAY", "daily"),
            ("WEEK", "weekly"),
            (None, "monthly"),  # observed default when unitText is absent
        ],
    )
    def test_pay_period_maps_to_the_canonical_enum(self, unit: str | None, period: str) -> None:
        cleaned = JobinjaCleaner().clean_job(_raw(salary_unit=unit))
        assert cleaned.pay_period == period

    def test_currency_prefers_json_ld_value(self) -> None:
        assert JobinjaCleaner().clean_job(_raw()).currency_iso_code == "IRT"

    def test_currency_falls_back_to_country_default(self) -> None:
        cleaned = JobinjaCleaner().clean_job(_raw(salary_currency=None, country_code="IR"))
        assert cleaned.currency_iso_code == "IRT"

    def test_unknown_country_falls_back_to_usd(self) -> None:
        cleaned = JobinjaCleaner().clean_job(_raw(salary_currency=None, country_code="XX"))
        assert cleaned.currency_iso_code == "USD"


class TestEmploymentType:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("FULL_TIME", "full_time"),
            ("PART_TIME", "part_time"),
            ("Intern", "internship"),
            ("temporary", "temporary"),
            ("CONTRACTOR", "contract"),
            ("VOLUNTEER", None),  # no ref code — honest None, not a guess
            ("PER_DIEM", None),
            (None, None),
        ],
    )
    def test_employment_maps_onto_ref_codes(self, raw: str | None, expected: str | None) -> None:
        cleaned = JobinjaCleaner().clean_job(_raw(employment_type_raw=raw))
        assert cleaned.employment_type_code == expected


class TestTextFields:
    def test_title_kept_in_source_language(self) -> None:
        cleaned = JobinjaCleaner().clean_job(_raw())
        assert cleaned.job_title == "کارشناس فروش بین المللی"

    def test_description_html_stripped(self) -> None:
        cleaned = JobinjaCleaner().clean_job(_raw())
        assert cleaned.description_clean == "توسعه نرم‌افزار و فروش بین‌المللی است."
        assert cleaned.word_count == len(cleaned.description_clean.split())

    def test_empty_description_is_none_with_zero_words(self) -> None:
        cleaned = JobinjaCleaner().clean_job(_raw(description_html=None))
        assert cleaned.description_clean is None
        assert cleaned.word_count == 0

    def test_skills_merge_category_lowercased_deduped(self) -> None:
        cleaned = JobinjaCleaner().clean_job(
            _raw(
                skills_spans=["فروش B2B", "CRM ", "crm"],
                category_spans=["فروش و بازاریابی"],
            )
        )
        assert cleaned.skills == ["فروش b2b", "crm", "فروش و بازاریابی"]

    def test_location_from_spans(self) -> None:
        cleaned = JobinjaCleaner().clean_job(_raw(location_spans=["تهران ، تهران"]))
        assert cleaned.location_cleaned == "تهران ، تهران"

    def test_missing_location_is_none(self) -> None:
        cleaned = JobinjaCleaner().clean_job(_raw(location_spans=[]))
        assert cleaned.location_cleaned is None

    def test_apply_url_is_the_job_url(self) -> None:
        # Jobinja's apply flow is login-gated; the page itself is the
        # honest apply target (same fallback stance Glints takes).
        cleaned = JobinjaCleaner().clean_job(_raw())
        assert cleaned.apply_url == URL
        assert cleaned.original_url == URL

    def test_raw_payload_passed_through_for_audit(self) -> None:
        payload = {"ld": {"@type": "JobPosting"}, "sections": {"حقوق": ["توافقی"]}}
        cleaned = JobinjaCleaner().clean_job(_raw(raw_payload=payload))
        assert cleaned.raw_payload == payload


class TestQualityScore:
    def test_every_signal_present_scores_one(self) -> None:
        cleaned = JobinjaCleaner().clean_job(
            _raw(description_html="<div>" + " ".join(["word"] * 30) + "</div>")
        )
        assert cleaned.data_quality_score == 1.0

    def test_no_salary_no_location_short_description_scores_low(self) -> None:
        cleaned = JobinjaCleaner().clean_job(
            _raw(
                salary_text_spans=[],
                base_salary_value=None,
                location_spans=[],
                skills_spans=[],
                category_spans=[],
                description_html="<div>کوتاه</div>",
            )
        )
        assert cleaned.data_quality_score == 0.0


class TestCleanJobsBatch:
    def test_batch_cleans_all_valid_records(self) -> None:
        jobs = JobinjaCleaner().clean_jobs([_raw(), _raw(source_job_id="1111728")])
        assert len(jobs) == 2

    def test_empty_batch(self) -> None:
        assert JobinjaCleaner().clean_jobs([]) == []
