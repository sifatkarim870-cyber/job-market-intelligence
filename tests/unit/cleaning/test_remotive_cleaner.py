"""Unit tests for job_market_intel.cleaning.remotive_cleaner.

Mirrors ``cleaning/test_remoteok_cleaner.py``'s coverage and rationale
closely — see that module's docstring for the shared principles. Genuine
differences, following directly from ``RemotiveCleaner``'s own module
docstring:

    - No ``TestSalaryBoundRepair`` class: there is nothing to swap.
      ``RawRemotiveJob``'s own model-level parsing already produces
      ``salary_min <= salary_max`` whenever it parses anything at all (or
      leaves both ``None``) — see ``test_models.py``'s
      ``TestSalaryRangeParsing`` for coverage of that parsing itself.
    - ``TestTagCleaning`` uses the ``tags`` field name (Remotive's own),
      not RemoteOK's ``tags`` field of the same name but different raw
      shape.
    - ``closing_date`` is asserted to always be ``None`` — Remotive has no
      posting-expiration field.
"""

from __future__ import annotations

from job_market_intel.cleaning.remotive_cleaner import RemotiveCleaner

# The RawRemotiveJob factory used below (`make_raw_remotive_job`) is the
# shared, root-level fixture in tests/conftest.py.


class TestTagCleaning:
    def test_tags_are_lowercased(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(tags=["Python", "Django"])
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.skills == ["python", "django"]

    def test_duplicate_tags_are_removed_case_insensitively(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(tags=["Python", "python", "PYTHON", "Django"])
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.skills == ["python", "django"]

    def test_whitespace_only_tags_are_dropped(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(tags=["python", "   ", ""])
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.skills == ["python"]

    def test_empty_tags_list_stays_empty(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(tags=[])
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.skills == []


class TestSalaryDisclosed:
    """Whether salary_disclosed follows correctly from whatever RawRemotiveJob already parsed."""

    def test_parsed_range_is_disclosed(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(salary="$100,000 - $150,000")
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.salary_disclosed is True
        assert cleaned.salary_min == 100000
        assert cleaned.salary_max == 150000

    def test_unparseable_salary_text_is_not_disclosed(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(salary="Competitive")
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.salary_disclosed is False
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None

    def test_missing_salary_field_is_not_disclosed(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(salary=None)
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.salary_disclosed is False


class TestClosingDateAlwaysNone:
    """Remotive's API has no posting-expiration field — see the cleaner's module docstring."""

    def test_closing_date_is_always_none(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job()
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.closing_date is None


class TestDescriptionAndWordCount:
    def test_html_description_is_cleaned(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(description="<p>We are <b>hiring</b> now.</p>")
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.description_clean == "We are hiring now."

    def test_word_count_matches_cleaned_text_not_raw_html(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(description="<p>One two three four</p>")
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.word_count == 4

    def test_missing_description_has_zero_word_count(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(description=None)
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.description_clean is None
        assert cleaned.word_count == 0


class TestLocationCleaning:
    def test_whitespace_is_trimmed(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(candidate_required_location="  USA  ")
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.location_cleaned == "USA"

    def test_html_entity_is_decoded(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(candidate_required_location="USA &amp; Canada")
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.location_cleaned == "USA & Canada"

    def test_none_location_stays_none(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(candidate_required_location=None)
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.location_cleaned is None


class TestPassThroughFields:
    def test_source_job_id_is_unchanged(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(id=1000042)
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.source_job_id == "1000042"

    def test_raw_payload_is_carried_forward(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job()
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.raw_payload == raw.raw_payload

    def test_original_url_is_unchanged(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(url="https://remotive.com/remote-jobs/1")
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.original_url == "https://remotive.com/remote-jobs/1"

    def test_apply_url_falls_back_to_original_url(self, make_raw_remotive_job) -> None:
        # Remotive offers no separate apply URL — same fallback WWR uses.
        raw = make_raw_remotive_job(url="https://remotive.com/remote-jobs/1")
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.apply_url == "https://remotive.com/remote-jobs/1"


class TestCleanJobsBatch:
    def test_batch_of_valid_jobs_all_clean_successfully(self, make_raw_remotive_job) -> None:
        raw_jobs = [make_raw_remotive_job(id=i) for i in range(5)]
        cleaned = RemotiveCleaner().clean_jobs(raw_jobs)
        assert len(cleaned) == 5

    def test_empty_batch_returns_empty_list(self) -> None:
        assert RemotiveCleaner().clean_jobs([]) == []


class TestDataQualityScore:
    """Verifies the completeness score uses the same four-signal formula as the other cleaners."""

    def test_fully_complete_job_scores_1(self, make_raw_remotive_job) -> None:
        substantial_description = "<p>" + " ".join(["word"] * 30) + "</p>"
        raw = make_raw_remotive_job(
            salary="$100,000 - $150,000",
            candidate_required_location="Worldwide",
            tags=["python"],
            description=substantial_description,
        )
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.data_quality_score == 1.0

    def test_fully_empty_job_scores_0(self, make_raw_remotive_job) -> None:
        raw = make_raw_remotive_job(
            salary=None,
            candidate_required_location=None,
            tags=[],
            description=None,
        )
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.data_quality_score == 0.0

    def test_partial_completeness_scores_proportionally(self, make_raw_remotive_job) -> None:
        # Salary + location present (2 of 4 signals), no tags, no description.
        raw = make_raw_remotive_job(
            salary="$100,000 - $150,000",
            candidate_required_location="Worldwide",
            tags=[],
            description=None,
        )
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.data_quality_score == 0.5

    def test_unparseable_salary_counts_against_completeness(self, make_raw_remotive_job) -> None:
        # A "Competitive"-style salary genuinely has information, but this
        # pipeline stage honestly cannot extract it — see the cleaner's
        # module docstring's note on this exact trade-off.
        substantial_description = "<p>" + " ".join(["word"] * 30) + "</p>"
        raw = make_raw_remotive_job(
            salary="Competitive",
            candidate_required_location="Worldwide",
            tags=["python"],
            description=substantial_description,
        )
        cleaned = RemotiveCleaner().clean_job(raw)
        assert cleaned.data_quality_score == 0.75
