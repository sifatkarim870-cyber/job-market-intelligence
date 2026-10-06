"""Unit tests for job_market_intel.cleaning.glints_cleaner.

Pins the Glints-specific decisions: Draft.js JSON descriptions become
plain text (with an HTML fallback for shape drift), salary disclosure
follows ``shouldShowSalary``, currency/pay-period always resolve to the
market's real values (the two ``CleanedJob`` fields are required), the
``type`` enum maps honestly to ``employment_type_code``, and tags land
as lowercased de-duplicated skills — on top of the four-signal quality
score every cleaner shares.
"""

from __future__ import annotations

import json

from job_market_intel.cleaning.glints_cleaner import GlintsCleaner


def _clean(job):
    return GlintsCleaner().clean_job(job)


class TestDescriptionCleaning:
    def test_draftjs_blocks_become_plain_text(self, make_raw_glints_job) -> None:
        payload = {
            "blocks": [
                {"text": "We are hiring a mechanic."},
                {"text": "Immediate start, Jakarta location."},
            ],
            "entityMap": {},
        }
        cleaned = _clean(make_raw_glints_job(description_raw=json.dumps(payload)))
        assert cleaned.description_clean == (
            "We are hiring a mechanic. Immediate start, Jakarta location."
        )
        assert cleaned.word_count == 9

    def test_empty_document_is_none_not_empty_string(self, make_raw_glints_job) -> None:
        payload = {"blocks": [], "entityMap": {}}
        cleaned = _clean(make_raw_glints_job(description_raw=json.dumps(payload)))
        assert cleaned.description_clean is None
        assert cleaned.word_count == 0

    def test_non_json_payload_falls_back_to_html_cleaning(self, make_raw_glints_job) -> None:
        cleaned = _clean(make_raw_glints_job(description_raw="<p>Hello <b>team</b></p>"))
        assert cleaned.description_clean == "Hello team"

    def test_missing_description_is_none(self, make_raw_glints_job) -> None:
        cleaned = _clean(make_raw_glints_job(description_raw=None))
        assert cleaned.description_clean is None
        assert cleaned.word_count == 0


class TestSalaryHandling:
    def test_disclosed_salary_kept_with_currency_and_period(self, make_raw_glints_job) -> None:
        cleaned = _clean(make_raw_glints_job())
        assert cleaned.salary_min == 1000000
        assert cleaned.salary_max == 2000000
        assert cleaned.salary_disclosed is True
        assert cleaned.currency_iso_code == "IDR"
        assert cleaned.pay_period == "monthly"

    def test_should_show_salary_false_withholds(self, make_raw_glints_job) -> None:
        cleaned = _clean(make_raw_glints_job(should_show_salary=False))
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False
        # Currency stays the market's real currency even when withheld
        # (same stance HR.ge's cleaner takes with GEL).
        assert cleaned.currency_iso_code == "IDR"

    def test_currency_falls_back_to_country_when_absent(self, make_raw_glints_job) -> None:
        cleaned = _clean(make_raw_glints_job(salary_currency=None, country_code="VN"))
        assert cleaned.currency_iso_code == "VND"

    def test_currency_falls_back_to_url_country(self, make_raw_glints_job) -> None:
        # Sourced fallbacks can omit CountryCode — the canonical URL
        # still carries the country segment.
        cleaned = _clean(
            make_raw_glints_job(
                salary_currency=None,
                country_code=None,
                original_url="https://glints.com/sg/opportunities/jobs/x/1",
            )
        )
        assert cleaned.currency_iso_code == "SGD"

    def test_yearly_mode_maps_to_annually(self, make_raw_glints_job) -> None:
        cleaned = _clean(make_raw_glints_job(salary_mode="YEAR"))
        assert cleaned.pay_period == "annually"

    def test_missing_mode_defaults_to_monthly(self, make_raw_glints_job) -> None:
        cleaned = _clean(make_raw_glints_job(salary_mode=None))
        assert cleaned.pay_period == "monthly"


class TestEmploymentMapping:
    def test_full_time_maps(self, make_raw_glints_job) -> None:
        assert (
            _clean(make_raw_glints_job(contract_type_raw="FULL_TIME")).employment_type_code
            == "full_time"
        )

    def test_part_time_maps(self, make_raw_glints_job) -> None:
        assert (
            _clean(make_raw_glints_job(contract_type_raw="PART_TIME")).employment_type_code
            == "part_time"
        )

    def test_internship_maps(self, make_raw_glints_job) -> None:
        assert (
            _clean(make_raw_glints_job(contract_type_raw="INTERNSHIP")).employment_type_code
            == "internship"
        )

    def test_unknown_type_is_none_not_a_guess(self, make_raw_glints_job) -> None:
        assert (
            _clean(make_raw_glints_job(contract_type_raw="MYSTERY")).employment_type_code is None
        )

    def test_missing_type_is_none(self, make_raw_glints_job) -> None:
        assert _clean(make_raw_glints_job(contract_type_raw=None)).employment_type_code is None


class TestTagsAndUrls:
    def test_tags_are_lowercased_and_deduplicated(self, make_raw_glints_job) -> None:
        cleaned = _clean(make_raw_glints_job(tags=["Store Crew", "store crew", "AutoCAD"]))
        assert cleaned.skills == ["store crew", "autocad"]

    def test_external_apply_url_preferred(self, make_raw_glints_job) -> None:
        cleaned = _clean(make_raw_glints_job(external_apply_url="https://ats.example.com/apply"))
        assert cleaned.apply_url == "https://ats.example.com/apply"

    def test_apply_url_falls_back_to_original(self, make_raw_glints_job) -> None:
        job = make_raw_glints_job()
        assert _clean(job).apply_url == job.original_url


class TestQualityScore:
    def test_all_four_signals(self, make_raw_glints_job) -> None:
        cleaned = _clean(
            make_raw_glints_job(description_raw=json.dumps({
                "blocks": [{"text": " ".join(["word"] * 30)}],
                "entityMap": {},
            }))
        )
        assert cleaned.data_quality_score == 1.0

    def test_no_signals(self, make_raw_glints_job) -> None:
        cleaned = _clean(
            make_raw_glints_job(
                should_show_salary=False,
                location_raw=None,
                tags=[],
                description_raw=None,
            )
        )
        assert cleaned.data_quality_score == 0.0

    def test_half_signals(self, make_raw_glints_job) -> None:
        # salary + location yes; skills yes; description too short (<20 words).
        cleaned = _clean(
            make_raw_glints_job(description_raw=json.dumps({
                "blocks": [{"text": "short but real description text"}],
                "entityMap": {},
            }))
        )
        assert cleaned.data_quality_score == 0.75
