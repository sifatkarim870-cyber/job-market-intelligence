"""Unit tests for job_market_intel.cleaning.irantalent_cleaner.

Pins the Irantalent-specific decisions the module docstring documents:
salary bounds pass through in whole Toman (no scaling — unlike
Jobvision's millions), ``is_show_salary: false`` withholds, currency
is IRT with pay_period monthly, employment maps from
``employment_type.title`` (no internship flag exists on this source),
tags merge category + industry English-first, and apply_url falls back
to original_url (no linkOut field).

Raw jobs come from the ``make_raw_irantalent_job`` conftest factory (live
row 184579 snapshot), same convention as the other cleaner tests.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from job_market_intel.cleaning.irantalent_cleaner import IrantalentCleaner
from job_market_intel.scrapers.irantalent.models import RawIrantalentJob


def _clean(job: RawIrantalentJob):
    return IrantalentCleaner().clean_job(job)


class TestPassthroughs:
    def test_core_fields(self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]) -> None:
        cleaned = _clean(make_raw_irantalent_job())
        assert cleaned.source_job_id == "184579"
        assert cleaned.job_title == "Customer Success Specialist"
        assert cleaned.original_url == (
            "https://www.irantalent.com/en/job/customer-success-specialist/184579"
        )
        # No linkOut/apply field exists on this source — same fallback
        # Jobvision's cleaner uses.
        assert cleaned.apply_url == cleaned.original_url
        assert cleaned.posting_date == datetime(2026, 10, 6, 18, 5, 33, tzinfo=UTC)
        assert cleaned.closing_date is None  # expired_at null while live
        assert cleaned.company_name == "ایویز"  # display name, Persian-first

    def test_missing_closing_date_is_none(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        assert _clean(make_raw_irantalent_job(closing_date=None)).closing_date is None


class TestSalary:
    def test_whole_toman_bounds_pass_through_unscaled(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        cleaned = _clean(make_raw_irantalent_job())
        # 350,000,000 Toman as sent — the cleaner's job here is to
        # NOT scale (Jobvision's x1,000,000 belongs to its own units).
        assert cleaned.salary_min == 350_000_000
        assert cleaned.salary_max == 450_000_000
        assert cleaned.salary_disclosed is True

    def test_null_bounds_are_undisclosed(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        cleaned = _clean(
            make_raw_irantalent_job(
                salary_min_raw=None, salary_max_raw=None, salary_show_flag=False
            )
        )
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_flag_false_withholds_even_if_bounds_present(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        # Defensive rule (never observed live — flag-False rows carry
        # nulls): an explicit "don't show" beats stray numbers.
        cleaned = _clean(make_raw_irantalent_job(salary_show_flag=False))
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_zero_bound_means_unstated(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        cleaned = _clean(make_raw_irantalent_job(salary_min_raw=0, salary_max_raw=0))
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_reversed_bounds_are_swapped(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        cleaned = _clean(
            make_raw_irantalent_job(salary_min_raw=450_000_000, salary_max_raw=350_000_000)
        )
        assert cleaned.salary_min == 350_000_000
        assert cleaned.salary_max == 450_000_000

    def test_single_bound_still_discloses(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        cleaned = _clean(make_raw_irantalent_job(salary_max_raw=None))
        assert cleaned.salary_min == 350_000_000
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is True

    def test_currency_and_period_are_documented_defaults(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        cleaned = _clean(make_raw_irantalent_job())
        # Iran-only board quoting Toman monthly; no IRT conversion rate
        # yet (NULL normalization, non-fatal — pending user decision).
        assert cleaned.currency_iso_code == "IRT"
        assert cleaned.pay_period == "monthly"


class TestEmploymentMapping:
    def test_observed_titles_map(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        assert _clean(make_raw_irantalent_job()).employment_type_code == "full_time"
        assert (
            _clean(make_raw_irantalent_job(work_type_en="Part Time")).employment_type_code
            == "part_time"
        )
        assert (
            _clean(make_raw_irantalent_job(work_type_en="Freelance")).employment_type_code
            == "freelance"
        )

    def test_unrecognized_title_falls_through_to_none(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        # No guessing — the raw value stays in raw_payload.
        assert (
            _clean(
                make_raw_irantalent_job(work_type_en="Full Time Or Part Time")
            ).employment_type_code
            is None
        )

    def test_missing_title_is_none(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        assert _clean(make_raw_irantalent_job(work_type_en=None)).employment_type_code is None

    def test_internship_would_map_via_the_table(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        # No internship flag exists on this source (none in a 180-row
        # sample), but "Internship" maps via the table if it appears.
        assert (
            _clean(make_raw_irantalent_job(work_type_en="Internship")).employment_type_code
            == "internship"
        )


class TestTagsAndText:
    def test_category_and_industry_merge_lowercased_deduped(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        cleaned = _clean(make_raw_irantalent_job())
        assert cleaned.skills == [
            "customer success & support operations",
            "it, software and internet services",
        ]

    def test_duplicate_labels_collapse(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        cleaned = _clean(
            make_raw_irantalent_job(category_raws=["Accounting"], industry_raws=["accounting"])
        )
        assert cleaned.skills == ["accounting"]

    def test_empty_tag_sources_yield_empty_skills(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        cleaned = _clean(make_raw_irantalent_job(category_raws=[], industry_raws=[]))
        assert cleaned.skills == []

    def test_description_html_is_stripped_and_counted(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        cleaned = _clean(make_raw_irantalent_job())
        assert "<br>" not in (cleaned.description_clean or "")
        assert "Role Overview:" in (cleaned.description_clean or "")
        assert cleaned.word_count == len(cleaned.description_clean.split())

    def test_empty_description_is_none_with_zero_words(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        cleaned = _clean(make_raw_irantalent_job(description_html=None))
        assert cleaned.description_clean is None
        assert cleaned.word_count == 0

    def test_location_is_persian_cleaned(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        assert _clean(make_raw_irantalent_job()).location_cleaned == "تهران"

    def test_missing_location_is_none(
        self, make_raw_irantalent_job: Callable[..., RawIrantalentJob]
    ) -> None:
        assert _clean(make_raw_irantalent_job(location_text=None)).location_cleaned is None


def test_data_quality_score_uses_four_signals(
    make_raw_irantalent_job: Callable[..., RawIrantalentJob],
) -> None:
    # Healthy job: disclosed salary + location + tags + substantial
    # description => 1.0. Same formula every cleaner uses.
    assert _clean(make_raw_irantalent_job()).data_quality_score == 1.0

    thin = _clean(
        make_raw_irantalent_job(
            salary_min_raw=None,
            salary_max_raw=None,
            salary_show_flag=None,
            location_text=None,
            description_html="short",
        )
    )
    # No salary + no location + tags still present + thin description
    # => 0.25.
    assert thin.data_quality_score == 0.25
