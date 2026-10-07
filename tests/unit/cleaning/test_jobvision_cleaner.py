"""Unit tests for job_market_intel.cleaning.jobvision_cleaner.

Pins the Jobvision-specific decisions: salary bounds scale from
**millions of Toman** to whole Toman (×1,000,000), null salary means
undisclosed, ≤0 means "bound unstated", reversed pairs are swapped,
currency resolves to IRT from the تومان text or the ایران country
anchor (USD + warning only when neither exists), ``workType.titleEn``
maps honestly onto ``employment_type_code`` with ``isInternship``
authoritative — plus the four-signal quality score every cleaner
shares.
"""

from __future__ import annotations

from job_market_intel.cleaning.jobvision_cleaner import JobvisionCleaner


def _clean(job):
    return JobvisionCleaner().clean_job(job)


class TestDescriptionCleaning:
    def test_html_becomes_text(self, make_raw_jobvision_job) -> None:
        cleaned = _clean(make_raw_jobvision_job())
        assert cleaned.description_clean == (
            "مسئولیت امور اداری و پشتیبانی بخش فروش تایپ و تنظیم اسناد و مکاتبات"
        )

    def test_missing_description_is_none(self, make_raw_jobvision_job) -> None:
        cleaned = _clean(make_raw_jobvision_job(description_html=None))
        assert cleaned.description_clean is None
        assert cleaned.word_count == 0


class TestSalaryScaling:
    def test_millions_become_whole_toman(self, make_raw_jobvision_job) -> None:
        cleaned = _clean(make_raw_jobvision_job())
        # Raw source units 26–30 million Toman → 26,000,000–30,000,000.
        assert cleaned.salary_min == 26_000_000
        assert cleaned.salary_max == 30_000_000
        assert cleaned.salary_disclosed is True

    def test_currency_and_period_from_market_evidence(
        self, make_raw_jobvision_job
    ) -> None:
        cleaned = _clean(make_raw_jobvision_job())
        # titleFa carries تومان → IRT; Iranian ads quote monthly.
        assert cleaned.currency_iso_code == "IRT"
        assert cleaned.pay_period == "monthly"

    def test_null_salary_is_undisclosed_but_currency_stays_irt(
        self, make_raw_jobvision_job
    ) -> None:
        cleaned = _clean(
            make_raw_jobvision_job(
                salary_min_raw=None, salary_max_raw=None, salary_title_fa=None
            )
        )
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False
        # No تومان text — the ایران country anchor still says IRT
        # (currency is required even when the figure is withheld).
        assert cleaned.currency_iso_code == "IRT"

    def test_zero_bound_means_unstated_not_zero(self, make_raw_jobvision_job) -> None:
        cleaned = _clean(make_raw_jobvision_job(salary_min_raw=0))
        assert cleaned.salary_min is None
        assert cleaned.salary_max == 30_000_000
        assert cleaned.salary_disclosed is True

    def test_both_bounds_zero_is_undisclosed(self, make_raw_jobvision_job) -> None:
        cleaned = _clean(
            make_raw_jobvision_job(salary_min_raw=0, salary_max_raw=0)
        )
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_reversed_range_is_swapped_not_dropped(
        self, make_raw_jobvision_job
    ) -> None:
        cleaned = _clean(make_raw_jobvision_job(salary_min_raw=40, salary_max_raw=30))
        assert cleaned.salary_min == 30_000_000
        assert cleaned.salary_max == 40_000_000
        assert cleaned.salary_disclosed is True

    def test_currency_falls_back_to_usd_with_warning_when_no_evidence(
        self, make_raw_jobvision_job
    ) -> None:
        # Never observed live (site is Iran-only); the fallback exists
        # so unexpected payload drift degrades instead of crashing.
        cleaned = _clean(
            make_raw_jobvision_job(salary_title_fa=None, country_fa="کانادا")
        )
        assert cleaned.currency_iso_code == "USD"


class TestEmploymentMapping:
    def test_full_time_maps(self, make_raw_jobvision_job) -> None:
        assert (
            _clean(make_raw_jobvision_job(work_type_en="Full Time")).employment_type_code
            == "full_time"
        )

    def test_part_time_maps(self, make_raw_jobvision_job) -> None:
        assert (
            _clean(make_raw_jobvision_job(work_type_en="Part Time")).employment_type_code
            == "part_time"
        )

    def test_hybrid_has_no_ref_code_so_is_none(
        self, make_raw_jobvision_job
    ) -> None:
        # "Full Time Or Part Time" (2/25 sampled): the ref enum has no
        # hybrid code and guessing full_time would be a lie.
        assert (
            _clean(
                make_raw_jobvision_job(work_type_en="Full Time Or Part Time")
            ).employment_type_code
            is None
        )

    def test_internship_flag_overrides_work_type(
        self, make_raw_jobvision_job
    ) -> None:
        assert (
            _clean(make_raw_jobvision_job(is_internship=True)).employment_type_code
            == "internship"
        )

    def test_missing_work_type_is_none(self, make_raw_jobvision_job) -> None:
        assert _clean(make_raw_jobvision_job(work_type_en=None)).employment_type_code is None

    def test_unknown_work_type_is_none_not_a_guess(
        self, make_raw_jobvision_job
    ) -> None:
        assert (
            _clean(make_raw_jobvision_job(work_type_en="MYSTERY")).employment_type_code
            is None
        )


class TestTagsLocationAndUrls:
    def test_five_sources_merge_lowercased_deduplicated(
        self, make_raw_jobvision_job
    ) -> None:
        cleaned = _clean(
            make_raw_jobvision_job(
                category_raws=["فروش و بازاریابی"],
                software_names=["Microsoft Excel", "microsoft excel"],
                language_names=["انگلیسی"],
                industry_raws=["تولیدی / صنعتی"],
                skills_raws=[],
            )
        )
        assert cleaned.skills == [
            "فروش و بازاریابی",
            "microsoft excel",
            "انگلیسی",
            "تولیدی / صنعتی",
        ]

    def test_location_pieces_joined(self, make_raw_jobvision_job) -> None:
        cleaned = _clean(make_raw_jobvision_job(location_parts=["گرمدره", "البرز"]))
        assert cleaned.location_cleaned == "گرمدره, البرز"

    def test_no_location_is_none(self, make_raw_jobvision_job) -> None:
        assert _clean(make_raw_jobvision_job(location_parts=[])).location_cleaned is None

    def test_external_apply_url_preferred(self, make_raw_jobvision_job) -> None:
        cleaned = _clean(
            make_raw_jobvision_job(link_out_address="https://apply.example.com/x")
        )
        assert cleaned.apply_url == "https://apply.example.com/x"

    def test_apply_url_falls_back_to_sitemap_url(self, make_raw_jobvision_job) -> None:
        job = make_raw_jobvision_job()
        assert _clean(job).apply_url == job.original_url

    def test_logo_passes_through(self, make_raw_jobvision_job) -> None:
        logo = make_raw_jobvision_job().company_logo_url
        assert _clean(make_raw_jobvision_job()).company_logo_url == logo

    def test_job_title_and_company_survive_cleaning(
        self, make_raw_jobvision_job
    ) -> None:
        cleaned = _clean(make_raw_jobvision_job())
        assert cleaned.job_title == "کارمند اداری - خانم"
        assert cleaned.company_name == "مجموعه چاپ سجادی"


class TestQualityScore:
    def test_defaults_are_three_of_four(self, make_raw_jobvision_job) -> None:
        # salary + location + skills yes; the default description is
        # short (<20 words) — so 0.75.
        assert _clean(make_raw_jobvision_job()).data_quality_score == 0.75

    def test_long_description_completes_the_score(
        self, make_raw_jobvision_job
    ) -> None:
        long_desc = "<p>" + " ".join(["word"] * 30) + "</p>"
        assert (
            _clean(make_raw_jobvision_job(description_html=long_desc)).data_quality_score
            == 1.0
        )

    def test_no_signals(self, make_raw_jobvision_job) -> None:
        cleaned = _clean(
            make_raw_jobvision_job(
                salary_min_raw=None,
                salary_max_raw=None,
                salary_title_fa=None,
                location_parts=[],
                category_raws=[],
                software_names=[],
                language_names=[],
                industry_raws=[],
                skills_raws=[],
                description_html=None,
            )
        )
        assert cleaned.data_quality_score == 0.0
