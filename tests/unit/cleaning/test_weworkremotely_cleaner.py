"""Unit tests for job_market_intel.cleaning.weworkremotely_cleaner.

Mirrors ``cleaning/test_remoteok_cleaner.py``'s structure and reasoning
exactly for everything shared (skills cleaning, description/word-count
handling, pass-through fields, batch behavior). What's new here is
coverage for the genuine structural differences documented in
``weworkremotely_cleaner.py``'s module docstring:
    - The "To apply: <url>" trailer strip.
    - Joining three raw location signals into one string.
    - Salary is always None/False, unconditionally — there's no swap
      logic to test because there's nothing to swap.
    - The data-quality score's honest 0.75 ceiling (since
      salary_disclosed can never be True for this source).
"""

from __future__ import annotations

from job_market_intel.cleaning.weworkremotely_cleaner import WWRCleaner

# The RawWWRJob factory used below (`make_raw_wwr_job`) is the shared,
# root-level fixture in tests/conftest.py.


class TestApplyTrailerStripping:
    def test_to_apply_trailer_is_removed(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(
            description=(
                "<p>Do engineering things.</p>"
                "<p>To apply: https://weworkremotely.com/remote-jobs/acme-corp-engineer</p>"
            )
        )
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.description_clean == "Do engineering things."
        assert "To apply" not in cleaned.description_clean

    def test_description_without_trailer_is_unaffected(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(description="<p>Do engineering things.</p>")
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.description_clean == "Do engineering things."

    def test_trailer_removal_is_case_insensitive(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(
            description="<p>Details here.</p><p>to apply: https://weworkremotely.com/x</p>"
        )
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.description_clean is not None
        assert "apply" not in cleaned.description_clean.lower()

    def test_description_that_is_only_a_trailer_becomes_none(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(
            description="<p>To apply: https://weworkremotely.com/remote-jobs/acme-corp-engineer</p>"
        )
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.description_clean is None
        assert cleaned.word_count == 0


class TestLocationJoining:
    def test_all_three_signals_present_are_joined(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(region="Anywhere in the World", country="Argentina", state="Texas")
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.location_cleaned == "Anywhere in the World; Argentina; Texas"

    def test_only_region_present(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(region="Anywhere in the World", country="", state="")
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.location_cleaned == "Anywhere in the World"

    def test_all_three_absent_yields_none(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(region=None, country=None, state=None)
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.location_cleaned is None

    def test_state_is_not_special_cased_out_even_though_unreliable(self, make_raw_wwr_job) -> None:
        # Per the module docstring: state_raw's reliability is uncertain,
        # but it is deliberately NOT dropped or treated differently from
        # region/country -- this is a direct check that no such
        # special-casing crept in.
        raw = make_raw_wwr_job(region=None, country=None, state="Delaware")
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.location_cleaned == "Delaware"


class TestSkillsCleaning:
    def test_skills_are_lowercased(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(skills="Python, Django")
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.skills == ["python", "django"]

    def test_duplicate_skills_removed_case_insensitively(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(skills="Python, python, PYTHON, Django")
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.skills == ["python", "django"]

    def test_empty_skills_string_stays_empty(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(skills="")
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.skills == []


class TestNoSalaryHandling:
    def test_salary_min_max_are_always_none(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job()
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None

    def test_salary_disclosed_is_always_false(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job()
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.salary_disclosed is False


class TestPassThroughFields:
    def test_source_job_id_is_the_extracted_slug(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(guid="https://weworkremotely.com/remote-jobs/acme-corp-engineer")
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.source_job_id == "acme-corp-engineer"

    def test_raw_payload_is_carried_forward(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job()
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.raw_payload == raw.raw_payload

    def test_apply_url_falls_back_to_original_url(self, make_raw_wwr_job) -> None:
        # WWR offers no distinct apply URL -- the job page URL serves
        # double duty, same fallback RemoteOKCleaner documents.
        raw = make_raw_wwr_job(link="https://weworkremotely.com/remote-jobs/acme-corp-engineer")
        cleaned = WWRCleaner().clean_job(raw)
        assert (
            cleaned.apply_url
            == cleaned.original_url
            == "https://weworkremotely.com/remote-jobs/acme-corp-engineer"
        )

    def test_closing_date_is_passed_through(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(expires_at="Thu, 24 Sep 2026 07:31:11 +0000")
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.closing_date is not None
        assert cleaned.closing_date == raw.closing_date

    def test_none_closing_date_stays_none(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(expires_at=None)
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.closing_date is None


class TestCleanJobsBatch:
    def test_batch_of_valid_jobs_all_clean_successfully(self, make_raw_wwr_job) -> None:
        raw_jobs = [
            make_raw_wwr_job(
                guid=f"https://weworkremotely.com/remote-jobs/job-{i}",
                link=f"https://weworkremotely.com/remote-jobs/job-{i}",
            )
            for i in range(5)
        ]
        cleaned = WWRCleaner().clean_jobs(raw_jobs)
        assert len(cleaned) == 5

    def test_empty_batch_returns_empty_list(self) -> None:
        assert WWRCleaner().clean_jobs([]) == []


class TestDataQualityScore:
    """Verifies the completeness score, and specifically its honest 0.75
    ceiling for this source (see the module docstring: salary_disclosed
    can never be True for We Work Remotely, so a "fully complete" WWR job
    can only ever reach 3 of the 4 signals, not 4)."""

    def test_fully_complete_job_is_capped_at_0_75_not_1(self, make_raw_wwr_job) -> None:
        substantial_description = "<p>" + " ".join(["word"] * 30) + "</p>"
        raw = make_raw_wwr_job(
            region="Anywhere in the World",
            skills="python, django",
            description=substantial_description,
        )
        cleaned = WWRCleaner().clean_job(raw)
        # location + skills + substantial description = 3 of 4 signals;
        # salary_disclosed is structurally always False for this source.
        assert cleaned.data_quality_score == 0.75

    def test_fully_empty_job_scores_0(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(
            region=None,
            country=None,
            state=None,
            skills="",
            description=None,
        )
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.data_quality_score == 0.0

    def test_short_description_does_not_count_as_substantial(self, make_raw_wwr_job) -> None:
        raw = make_raw_wwr_job(
            region=None,
            country=None,
            state=None,
            skills="",
            description="<p>Short.</p>",
        )
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.data_quality_score == 0.0

    def test_partial_completeness_scores_proportionally(self, make_raw_wwr_job) -> None:
        # Location present (1 of 4 signals), no skills, no description.
        raw = make_raw_wwr_job(
            region="Anywhere in the World",
            country=None,
            state=None,
            skills="",
            description=None,
        )
        cleaned = WWRCleaner().clean_job(raw)
        assert cleaned.data_quality_score == 0.25
