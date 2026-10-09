"""Unit tests for the Greenhouse scraper.

Each test here pins a bug that actually occurred while building this source.
Building it against live endpoints, in order:

  1. ``internal_job_id`` arrives as an int, so a ``str | None`` field rejected
     100% of real postings -- 1,000 of 1,000 dropped before a single row
     reached the database.
  2. ``metadata``/``departments``/``offices`` arrive as JSON ``null``, not
     ``[]``. A pydantic ``default_factory`` only covers a MISSING key, so the
     first live run parsed 269 of 1,000 and dropped 731.
  3. ``content`` is HTML that has itself been entity-escaped, so the shared
     ``clean_html_text`` decodes it to literal tags instead of stripping them,
     and raw ``<div>`` markup lands in ``description_clean``.

Run with:  uv run python -m pytest tests/unit/scrapers/test_greenhouse.py
"""

from __future__ import annotations

import html

import pytest

from job_market_intel.cleaning.greenhouse_cleaner import GreenhouseCleaner
from job_market_intel.scrapers.greenhouse.config import GreenhouseSettings
from job_market_intel.scrapers.greenhouse.models import RawGreenhouseJob
from job_market_intel.scrapers.greenhouse.parser import GreenhouseParser


def _payload(**overrides) -> dict:
    """A minimal but realistic posting, as Greenhouse actually returns one."""
    base = {
        "id": 8860302002,
        "title": "Account Executive - France",
        "updated_at": "2026-10-02T11:31:50-04:00",
        "absolute_url": "https://job-boards.greenhouse.io/gitlab/jobs/8860302002",
        "location": {"name": "Remote, France"},
        "departments": [{"id": 1, "name": "EMEA - Commercial", "parent_id": None}],
        "offices": [{"id": 2, "name": "France", "location": "France"}],
        "metadata": [{"id": 3, "name": "Quota Coverage Type", "value": "AE"}],
        "company_name": "GitLab",
        "internal_job_id": 6547054002,
        "requisition_id": 7109,
        "language": "en",
        "content": "&lt;div class=&quot;x&quot;&gt;&lt;p&gt;Build things.&lt;/p&gt;&lt;/div&gt;",
    }
    base.update(overrides)
    return base


class TestRawGreenhouseJob:
    def test_numeric_ids_are_coerced_to_strings(self):
        """Regression 1: id/internal_job_id/requisition_id arrive as ints."""
        job = RawGreenhouseJob.model_validate(_payload())
        assert job.source_job_id == "8860302002"
        assert isinstance(job.source_job_id, str)
        assert job.internal_job_id == "6547054002"
        assert job.requisition_id == "7109"

    def test_null_collections_become_empty(self):
        """Regression 2: these keys are present-but-null on real boards."""
        job = RawGreenhouseJob.model_validate(
            _payload(metadata=None, departments=None, offices=None, location=None)
        )
        assert job.metadata == []
        assert job.departments == []
        assert job.offices == []
        assert job.location == {}

    def test_null_is_distinguished_per_field_type(self):
        """location is a dict; the rest are lists. Both must not become []."""
        job = RawGreenhouseJob.model_validate(_payload(location=None, metadata=None))
        assert job.location == {}
        assert job.metadata == []

    def test_helpers_expose_nested_names(self):
        job = RawGreenhouseJob.model_validate(_payload())
        assert job.location_name == "Remote, France"
        assert job.office_names == ["France"]
        assert job.department_names == ["EMEA - Commercial"]


class TestGreenhouseParser:
    def test_parses_a_realistic_record(self):
        jobs, issues = GreenhouseParser().parse_jobs([_payload()])
        assert len(jobs) == 1
        assert issues == []

    def test_one_bad_record_does_not_lose_the_batch(self):
        good = _payload(id=1, title="Kept")
        bad = {"id": None, "title": "No id"}
        jobs, issues = GreenhouseParser().parse_jobs([good, bad])
        assert len(jobs) == 1
        assert len(issues) == 1

    def test_empty_title_is_rejected(self):
        """A posting with no title is not a job posting.

        min_length=1 rejects "" but not whitespace, which is deliberate: a
        whitespace-only title is not a real occurrence on any board, and
        rejecting it would mean a validator on a field the source already
        constrains. Pinned here so the boundary is a decision, not an accident.
        """
        jobs, issues = GreenhouseParser().parse_jobs([_payload(title="")])
        assert jobs == []
        assert len(issues) == 1


class TestGreenhouseCleaner:
    def test_double_encoded_html_is_fully_stripped(self):
        """Regression 3: content is escaped HTML, not raw markup."""
        cleaned = GreenhouseCleaner().clean_job(RawGreenhouseJob.model_validate(_payload()))
        assert cleaned.description_clean == "Build things."
        assert "<" not in cleaned.description_clean

    def test_escaped_entities_inside_text_survive_once(self):
        payload = _payload(content="&lt;p&gt;Uses R&amp;D and C++&lt;/p&gt;")
        cleaned = GreenhouseCleaner().clean_job(RawGreenhouseJob.model_validate(payload))
        assert cleaned.description_clean == "Uses R&D and C++"

    def test_vague_remote_location_falls_back_to_office(self):
        """'Remote' alone resolves to nothing; offices usually carry the country."""
        payload = _payload(
            location={"name": "Remote"}, offices=[{"id": 2, "name": "Netherlands"}]
        )
        cleaned = GreenhouseCleaner().clean_job(RawGreenhouseJob.model_validate(payload))
        assert cleaned.location_cleaned == "Netherlands"

    def test_specific_location_is_kept(self):
        cleaned = GreenhouseCleaner().clean_job(RawGreenhouseJob.model_validate(_payload()))
        assert cleaned.location_cleaned == "Remote, France"

    def test_no_salary_is_claimed(self):
        """Greenhouse publishes no compensation; saying so beats inventing one."""
        cleaned = GreenhouseCleaner().clean_job(RawGreenhouseJob.model_validate(_payload()))
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_closing_date_stays_none(self):
        """Greenhouse has no expiry field; leaving it None is the honest value."""
        cleaned = GreenhouseCleaner().clean_job(RawGreenhouseJob.model_validate(_payload()))
        assert cleaned.closing_date is None

    def test_quality_score_reflects_what_the_source_actually_has(self):
        """Four signals: salary, location, skills, substantial description.

        The default payload has a location but a 2-word description, and no
        salary and no departments -> 1 of 4 = 0.25. Greenhouse will routinely
        score below a job board here because it publishes no salary at all;
        that is an accurate reading of the source, not a bug.
        """
        cleaned = GreenhouseCleaner().clean_job(
            RawGreenhouseJob.model_validate(_payload(departments=[]))
        )
        assert cleaned.word_count < 50
        assert cleaned.location_cleaned is not None
        assert cleaned.skills == []
        assert cleaned.data_quality_score == 0.25

    def test_quality_score_rises_with_a_substantial_description(self):
        long_content = "&lt;p&gt;" + ("detailed responsibilities " * 40) + "&lt;/p&gt;"
        cleaned = GreenhouseCleaner().clean_job(
            RawGreenhouseJob.model_validate(_payload(content=long_content))
        )
        assert cleaned.word_count >= 50
        assert cleaned.data_quality_score == 0.75

    def test_source_job_id_is_the_greenhouse_id(self):
        cleaned = GreenhouseCleaner().clean_job(RawGreenhouseJob.model_validate(_payload()))
        assert cleaned.source_job_id == "8860302002"


class TestGreenhouseSettings:
    def test_comma_separated_slugs_from_env(self):
        """pydantic-settings parses complex types as JSON; a bare list must not
        blow up with a JSON decode error."""
        settings = GreenhouseSettings(company_slugs="alpha, beta ,gamma")
        assert settings.company_slugs == ["alpha", "beta", "gamma"]

    def test_board_url_requests_description_html(self):
        """Without content=true every posting has an empty description."""
        from job_market_intel.scrapers.greenhouse.client import GreenhouseClient

        url = GreenhouseClient(GreenhouseSettings()).board_url("gitlab")
        assert "content=true" in url
        assert url.endswith("/boards/gitlab/jobs?content=true")

    def test_defaults_cover_verified_boards_only(self):
        settings = GreenhouseSettings()
        assert "gitlab" in settings.company_slugs
        assert len(settings.company_slugs) >= 4


class TestValidatorChecks:
    def test_missing_field_checks_are_callables(self):
        """Regression: passing booleans raised "'bool' object is not callable"."""
        from job_market_intel.validation.greenhouse_validator import _MISSING_FIELD_CHECKS

        assert _MISSING_FIELD_CHECKS
        for name, check in _MISSING_FIELD_CHECKS.items():
            assert callable(check), f"{name} check must be callable, got {type(check)}"

    def test_title_check_flags_blank_title(self):
        from job_market_intel.validation.greenhouse_validator import _MISSING_FIELD_CHECKS

        job = RawGreenhouseJob.model_validate(_payload())
        assert _MISSING_FIELD_CHECKS["title"](job) is False
        # An empty title cannot be constructed (min_length=1), so blank the
        # field after validation -- which is exactly the state the check exists
        # to catch if a future board starts sending whitespace-only titles.
        assert _MISSING_FIELD_CHECKS["title"](job.model_copy(update={"title": ""})) is True

    def test_content_check_passes_real_content(self):
        from job_market_intel.validation.greenhouse_validator import _MISSING_FIELD_CHECKS

        job = RawGreenhouseJob.model_validate(_payload())
        assert _MISSING_FIELD_CHECKS["content"](job) is False


def test_html_unescape_is_the_documented_first_step():
    """Guards the double-encoding assumption itself, so a future Greenhouse
    change that stops escaping shows up here rather than as silent markup in
    description_clean."""
    raw = "&lt;p&gt;hi&lt;/p&gt;"
    assert "<p>" in html.unescape(raw)
    assert "<p>" not in raw


@pytest.mark.parametrize("slug", ["gitlab", "stripe"])
def test_board_url_shape(slug: str):
    from job_market_intel.scrapers.greenhouse.client import GreenhouseClient

    client_url = GreenhouseClient(GreenhouseSettings()).board_url(slug)
    assert client_url.startswith("https://boards-api.greenhouse.io/v1/boards/")
    assert client_url.endswith("/jobs?content=true")
