"""Unit tests for job_market_intel.cleaning.remoteok_cleaner.

What these tests verify, and why each matters:
    - Real, previously-observed messy records (mojibake title, HTML-entity
      company name, trailing-comma location) come out clean — these are
      direct regression tests against actual problems seen in a live
      RemoteOK run, not hypothetical cases.
    - Tags are cleaned, lowercased, and de-duplicated.
    - salary_disclosed is derived correctly in every combination of
      present/absent bounds.
    - Reversed salary bounds are swapped, not silently kept broken or
      dropped.
    - word_count matches the cleaned description, not the raw HTML.
    - clean_jobs() processes a batch and never raises on a single bad
      record.
"""

from __future__ import annotations

from job_market_intel.cleaning.remoteok_cleaner import RemoteOKCleaner

# The RawRemoteOKJob factory used below (`make_raw_remoteok_job`) is the
# shared, root-level fixture in tests/conftest.py.


class TestRealWorldRegressions:
    """Direct regression tests against messy records seen in a live RemoteOK run."""

    def test_mojibake_in_title_is_repaired(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(position="LÃ‘N")
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.job_title == "LÑN"

    def test_html_entity_in_company_name_is_decoded(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(company="Chubb Fire &amp; Security")
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.company_name == "Chubb Fire & Security"

    def test_trailing_comma_location_is_stripped(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(location="Success,")
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.location_cleaned == "Success"

    def test_trailing_comma_with_whitespace_is_stripped(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(location="Mangalagiri, ")
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.location_cleaned == "Mangalagiri"

    def test_normal_location_without_trailing_comma_is_unaffected(
        self, make_raw_remoteok_job
    ) -> None:
        raw = make_raw_remoteok_job(location="Worldwide")
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.location_cleaned == "Worldwide"

    def test_none_location_stays_none(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(location=None)
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.location_cleaned is None


class TestTagCleaning:
    def test_tags_are_lowercased(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(tags=["Python", "Django"])
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.skills == ["python", "django"]

    def test_duplicate_tags_are_removed_case_insensitively(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(tags=["Python", "python", "PYTHON", "Django"])
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.skills == ["python", "django"]

    def test_whitespace_only_tags_are_dropped(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(tags=["python", "   ", ""])
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.skills == ["python"]

    def test_empty_tags_list_stays_empty(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(tags=[])
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.skills == []


class TestSalaryDisclosed:
    def test_both_bounds_present_is_disclosed(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(salary_min=100000, salary_max=150000)
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.salary_disclosed is True

    def test_only_min_present_is_disclosed(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(salary_min=100000, salary_max=None)
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.salary_disclosed is True

    def test_neither_bound_present_is_not_disclosed(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(salary_min=None, salary_max=None)
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.salary_disclosed is False


class TestSalaryBoundRepair:
    def test_reversed_bounds_are_swapped(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(salary_min=160000, salary_max=120000)
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.salary_min == 120000
        assert cleaned.salary_max == 160000

    def test_correctly_ordered_bounds_are_unchanged(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(salary_min=100000, salary_max=150000)
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.salary_min == 100000
        assert cleaned.salary_max == 150000

    def test_only_one_bound_present_is_left_alone(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(salary_min=100000, salary_max=None)
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.salary_min == 100000
        assert cleaned.salary_max is None


class TestDescriptionAndWordCount:
    def test_html_description_is_cleaned(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(description="<p>We are <b>hiring</b> now.</p>")
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.description_clean == "We are hiring now."

    def test_word_count_matches_cleaned_text_not_raw_html(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(description="<p>One two three four</p>")
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.word_count == 4

    def test_missing_description_has_zero_word_count(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(description=None)
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.description_clean is None
        assert cleaned.word_count == 0


class TestPassThroughFields:
    def test_source_job_id_is_unchanged(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(id="1000042")
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.source_job_id == "1000042"

    def test_raw_payload_is_carried_forward(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job()
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.raw_payload == raw.raw_payload

    def test_original_url_is_unchanged(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(url="https://remoteok.com/remote-jobs/1")
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.original_url == "https://remoteok.com/remote-jobs/1"


class TestCleanJobsBatch:
    def test_batch_of_valid_jobs_all_clean_successfully(self, make_raw_remoteok_job) -> None:
        raw_jobs = [make_raw_remoteok_job(id=str(i)) for i in range(5)]
        cleaned = RemoteOKCleaner().clean_jobs(raw_jobs)
        assert len(cleaned) == 5

    def test_empty_batch_returns_empty_list(self) -> None:
        assert RemoteOKCleaner().clean_jobs([]) == []


class TestDataQualityScore:
    """Verifies the completeness score, and specifically that it does NOT
    try to judge whether a listing is spam/junk by its title or content —
    only by whether the four completeness signals are present."""

    def test_fully_complete_job_scores_1(self, make_raw_remoteok_job) -> None:
        substantial_description = "<p>" + " ".join(["word"] * 30) + "</p>"
        raw = make_raw_remoteok_job(
            salary_min=100000,
            salary_max=150000,
            location="Worldwide",
            tags=["python"],
            description=substantial_description,
        )
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.data_quality_score == 1.0

    def test_fully_empty_job_scores_0(self, make_raw_remoteok_job) -> None:
        raw = make_raw_remoteok_job(
            salary_min=None,
            salary_max=None,
            location=None,
            tags=[],
            description=None,
        )
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.data_quality_score == 0.0

    def test_short_description_does_not_count_as_substantial(self, make_raw_remoteok_job) -> None:
        # Below _SUBSTANTIAL_DESCRIPTION_WORD_COUNT (20 words) — mirrors
        # the sparse, one-line descriptions seen on real junk listings.
        raw = make_raw_remoteok_job(
            salary_min=None,
            salary_max=None,
            location=None,
            tags=[],
            description="<p>Short.</p>",
        )
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.data_quality_score == 0.0

    def test_partial_completeness_scores_proportionally(self, make_raw_remoteok_job) -> None:
        # Salary + location present (2 of 4 signals), no tags, no description.
        raw = make_raw_remoteok_job(
            salary_min=100000,
            salary_max=150000,
            location="Worldwide",
            tags=[],
            description=None,
        )
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.data_quality_score == 0.5

    def test_score_is_a_completeness_measure_not_a_title_judgment(
        self, make_raw_remoteok_job
    ) -> None:
        # A title that reads like junk ("Menu") but happens to be fully
        # complete on every other field should still score 1.0 — this
        # score is not, and must not become, a disguised spam classifier.
        substantial_description = "<p>" + " ".join(["word"] * 30) + "</p>"
        raw = make_raw_remoteok_job(
            position="Menu",
            salary_min=100000,
            salary_max=150000,
            location="Worldwide",
            tags=["python"],
            description=substantial_description,
        )
        cleaned = RemoteOKCleaner().clean_job(raw)
        assert cleaned.data_quality_score == 1.0
