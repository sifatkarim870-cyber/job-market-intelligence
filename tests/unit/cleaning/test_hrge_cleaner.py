"""Unit tests for job_market_intel.cleaning.hrge_cleaner.

What these tests verify, and why each matters:
    - The site's "This announcement is available only in Georgian
      Language, please see the text below (...)" notice is boilerplate,
      not job content: it must be stripped before word counting (live
      observation 2026-10-07 — every Georgian-only announcement served
      under Accept-Language: en carried it), while the Georgian body
      itself stays untouched for the translation layer.
    - Employment mapping: schedule first (``full_time``/``part_time``),
      contract-kind fallback (``fixed-term contract`` -> ``contract``),
      honest None for unrecognized values (observed live: "Mixed shifts"
      / "Open-ended contract") — never a guess.
    - Salary disclosure follows the observed flag semantics: amounts +
      showSalary=true = disclosed; showSalary=false or hideSalary=true
      = withheld even when amounts exist; GEL/monthly regardless.
    - Data quality is the shared four-signal formula.
    - Tags are cleaned, lowercased, de-duplicated.
"""

from __future__ import annotations

import pytest

from job_market_intel.cleaning.hrge_cleaner import HRGeCleaner

_GEO_NOTICE = (
    "This announcement is available only in Georgian Language, please see "
    "the text below (You can also switch the site Language from header "
    "language switcher)"
)
_GEO_BODY = "ჩვენ ვეძებთ პოზიტიურ და მოტივირებულ თანამშრომლებს სტუდიაში"
_RICH_DESC = (
    "We are looking for a positive and motivated colleague to join our "
    "friendly modern studio in tbilisi today with great benefits"
)


class TestGeorgianNoticeStripping:
    def test_notice_is_stripped_and_body_kept(self, make_raw_hrge_job) -> None:
        raw = make_raw_hrge_job(description_raw=f"<div>{_GEO_NOTICE} {_GEO_BODY}</div>")
        cleaned = HRGeCleaner().clean_job(raw)
        assert cleaned.description_clean == _GEO_BODY

    def test_notice_without_parenthetical_is_stripped(self, make_raw_hrge_job) -> None:
        notice = (
            "This announcement is available only in Georgian Language, "
            "please see the text below"
        )
        raw = make_raw_hrge_job(description_raw=f"<p>{notice} {_GEO_BODY}</p>")
        cleaned = HRGeCleaner().clean_job(raw)
        assert cleaned.description_clean == _GEO_BODY

    def test_english_description_is_untouched(self, make_raw_hrge_job) -> None:
        raw = make_raw_hrge_job(description_raw=f"<p>{_RICH_DESC}</p>")
        cleaned = HRGeCleaner().clean_job(raw)
        assert cleaned.description_clean == _RICH_DESC

    def test_word_count_is_taken_from_the_stripped_text(self, make_raw_hrge_job) -> None:
        raw = make_raw_hrge_job(description_raw=f"<div>{_GEO_NOTICE} {_GEO_BODY}</div>")
        cleaned = HRGeCleaner().clean_job(raw)
        assert cleaned.word_count == len(_GEO_BODY.split())


class TestEmploymentMapping:
    @pytest.mark.parametrize(
        ("schedule", "contract", "expected"),
        [
            ("Full-time", "Fixed-term contract", "full_time"),
            ("Part-time", "Fixed-term contract", "part_time"),
            ("Mixed shifts", "Open-ended contract", None),  # observed live
            (None, "Fixed-term contract", "contract"),
            (None, "Open-ended contract", None),
            ("Full-time", None, "full_time"),
            (None, None, None),
        ],
    )
    def test_schedule_first_then_contract_fallback(
        self, make_raw_hrge_job, schedule, contract, expected
    ) -> None:
        raw = make_raw_hrge_job(work_schedule_raw=schedule, contract_type_raw=contract)
        cleaned = HRGeCleaner().clean_job(raw)
        assert cleaned.employment_type_code == expected


class TestSalaryDisclosure:
    def test_amounts_with_show_true_are_disclosed(self, make_raw_hrge_job) -> None:
        raw = make_raw_hrge_job(salary_from_raw=1200, salary_to_raw=None, show_salary=True)
        cleaned = HRGeCleaner().clean_job(raw)
        assert cleaned.salary_disclosed is True
        assert cleaned.salary_min == 1200
        assert cleaned.salary_max is None

    def test_show_false_withholds_even_when_amounts_exist(self, make_raw_hrge_job) -> None:
        raw = make_raw_hrge_job(salary_from_raw=1200, salary_to_raw=1800, show_salary=False)
        cleaned = HRGeCleaner().clean_job(raw)
        assert cleaned.salary_disclosed is False
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None

    def test_hide_true_withholds(self, make_raw_hrge_job) -> None:
        raw = make_raw_hrge_job(salary_from_raw=900, show_salary=True, hide_salary=True)
        cleaned = HRGeCleaner().clean_job(raw)
        assert cleaned.salary_disclosed is False
        assert cleaned.salary_min is None

    def test_missing_flags_with_amounts_are_disclosed(self, make_raw_hrge_job) -> None:
        raw = make_raw_hrge_job(
            salary_from_raw=1200, salary_to_raw=1800, show_salary=None, hide_salary=None
        )
        cleaned = HRGeCleaner().clean_job(raw)
        assert cleaned.salary_disclosed is True
        assert (cleaned.salary_min, cleaned.salary_max) == (1200, 1800)

    def test_no_amounts_is_undisclosed(self, make_raw_hrge_job) -> None:
        raw = make_raw_hrge_job(salary_from_raw=None, salary_to_raw=None, show_salary=True)
        cleaned = HRGeCleaner().clean_job(raw)
        assert cleaned.salary_disclosed is False

    def test_georgian_market_currency_and_period(self, make_raw_hrge_job) -> None:
        raw = make_raw_hrge_job(salary_from_raw=1200, show_salary=True)
        cleaned = HRGeCleaner().clean_job(raw)
        assert cleaned.currency_iso_code == "GEL"
        assert cleaned.pay_period == "monthly"


class TestTagCleaning:
    def test_tags_are_lowercased_and_deduplicated(self, make_raw_hrge_job) -> None:
        raw = make_raw_hrge_job(tags=["Sales", "sales", "Retail"])
        cleaned = HRGeCleaner().clean_job(raw)
        assert cleaned.skills == ["sales", "retail"]


class TestDataQualityScore:
    def test_all_four_signals_score_one(self, make_raw_hrge_job) -> None:
        raw = make_raw_hrge_job(
            salary_from_raw=1200,
            show_salary=True,
            location_raw="Tbilisi",
            tags=["Sales"],
            description_raw=f"<p>{_RICH_DESC}</p>",
        )
        cleaned = HRGeCleaner().clean_job(raw)
        assert cleaned.data_quality_score == 1.0

    def test_no_signals_score_zero(self, make_raw_hrge_job) -> None:
        raw = make_raw_hrge_job(
            location_raw=None,
            tags=[],
            salary_from_raw=None,
            salary_to_raw=None,
            show_salary=False,
            description_raw=None,
        )
        cleaned = HRGeCleaner().clean_job(raw)
        assert cleaned.data_quality_score == 0.0

    def test_default_factory_job_is_half_rich(self, make_raw_hrge_job) -> None:
        # location + skills yes; salary undisclosed; description < 20 words.
        cleaned = HRGeCleaner().clean_job(make_raw_hrge_job())
        assert cleaned.data_quality_score == 0.5


class TestUrlsAndText:
    def test_apply_and_original_url_point_at_the_public_page(
        self, make_raw_hrge_job
    ) -> None:
        cleaned = HRGeCleaner().clean_job(make_raw_hrge_job())
        assert cleaned.original_url == "https://www.hr.ge/announcement/496982"
        assert cleaned.apply_url == cleaned.original_url

    def test_title_whitespace_is_trimmed(self, make_raw_hrge_job) -> None:
        cleaned = HRGeCleaner().clean_job(make_raw_hrge_job(job_title="Cashier/Consultant "))
        assert cleaned.job_title == "Cashier/Consultant"

    def test_batch_never_raises(self, make_raw_hrge_job) -> None:
        cleaned = HRGeCleaner().clean_jobs([make_raw_hrge_job(), make_raw_hrge_job()])
        assert len(cleaned) == 2
