"""Integration tests for We Work Remotely Pipeline & JobRepository (Step 17).

Tests live database storage, deduplication via content hashing, and pipeline
execution against a real, schema-applied PostgreSQL test instance.

The requires_live_db marker/skip behavior and the `db_session` fixture
(a transactional, pre-seeded ORM Session) are both centralized in
tests/integration/conftest.py — see that file's module docstring for why.

Mirrors test_remoteok_pipeline.py's structure exactly, with one addition:
TestClosingDateRoundTrip, verifying core.jobs.closing_date — a column no
prior source ever wrote to — actually round-trips through a real
PostgreSQL insert/read, not just through the mocked-Session unit tests in
tests/unit/db/test_job_repository.py.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.db.job_repository import JobRepository
from job_market_intel.scrapers.weworkremotely.pipeline import WWRPipeline

pytestmark = pytest.mark.requires_live_db


def _wwr_style_job(
    make_cleaned_job: Callable[..., CleanedJob],
    source_job_id: str = "acme-corp-990001",
    title: str = "Lead Backend Engineer",
    **overrides: Any,
) -> CleanedJob:
    """A realistic, fully-populated "We Work Remotely-shaped" CleanedJob,
    built on top of the shared `make_cleaned_job` fixture (see
    tests/conftest.py), same pattern test_remoteok_pipeline.py's
    `_remoteok_style_job` establishes.

    Differs from that preset in exactly the ways We Work Remotely's real
    output differs: no salary (salary_disclosed=False, both bounds None),
    location_cleaned shaped like this cleaner's joined-string output, and
    closing_date populated (a field RemoteOK's preset never sets).
    """
    defaults: dict[str, Any] = {
        "company_name": "Acme Corp",
        "company_logo_url": "https://wwr-pro.s3.amazonaws.com/logos/acme/logo.gif",
        "skills": ["python", "django", "postgres"],
        "location_cleaned": "Anywhere in the World; Argentina, Brazil",
        "salary_min": None,
        "salary_max": None,
        "salary_disclosed": False,
        "description_clean": (
            "We are looking for a Lead Backend Engineer to build scalable services."
        ),
        "word_count": 11,
        "apply_url": f"https://weworkremotely.com/remote-jobs/{source_job_id}",
        "original_url": f"https://weworkremotely.com/remote-jobs/{source_job_id}",
        "posting_date": datetime.now(UTC),
        "closing_date": datetime(2026, 12, 31, tzinfo=UTC),
        "data_quality_score": 0.75,
        "raw_payload": {"guid": source_job_id, "title": f"Acme Corp: {title}"},
    }
    defaults.update(overrides)
    return make_cleaned_job(source_job_id=source_job_id, job_title=title, **defaults)


class TestJobRepositoryIntegrationWWR:
    def test_save_cleaned_job_inserts_new_record(self, db_session, make_cleaned_job):
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "weworkremotely")
        session_id = repo.create_scraping_session(db_session, source_id)

        job = _wwr_style_job(make_cleaned_job, source_job_id="acme-corp-990001")
        status = repo.save_cleaned_job(db_session, job, source_id=source_id, session_id=session_id)

        assert status == "inserted"

        job_row = db_session.execute(
            text(
                "SELECT job_id, job_title, content_hash FROM core.jobs "
                "WHERE source_job_id = 'acme-corp-990001'"
            )
        ).first()
        assert job_row is not None
        assert job_row.job_title == "Lead Backend Engineer"

        desc_row = db_session.execute(
            text("SELECT word_count FROM core.job_descriptions WHERE job_id = :job_id"),
            {"job_id": job_row.job_id},
        ).first()
        assert desc_row is not None
        assert desc_row.word_count == 11

        # We Work Remotely jobs structurally have no salary -- confirm
        # the row exists (every job gets a salary.job_salaries row, per
        # the schema) but with everything null/false.
        salary_row = db_session.execute(
            text(
                "SELECT salary_min, salary_max, salary_disclosed "
                "FROM salary.job_salaries WHERE job_id = :job_id"
            ),
            {"job_id": job_row.job_id},
        ).first()
        assert salary_row is not None
        assert salary_row.salary_min is None
        assert salary_row.salary_max is None
        assert salary_row.salary_disclosed is False

    def test_save_cleaned_job_detects_unchanged_record(self, db_session, make_cleaned_job):
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "weworkremotely")
        session_id = repo.create_scraping_session(db_session, source_id)

        job = _wwr_style_job(make_cleaned_job, source_job_id="acme-corp-990002")
        status_1 = repo.save_cleaned_job(
            db_session, job, source_id=source_id, session_id=session_id
        )
        assert status_1 == "inserted"

        status_2 = repo.save_cleaned_job(
            db_session, job, source_id=source_id, session_id=session_id
        )
        assert status_2 == "unchanged"

    def test_save_cleaned_job_detects_updated_record(self, db_session, make_cleaned_job):
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "weworkremotely")
        session_id = repo.create_scraping_session(db_session, source_id)

        job_initial = _wwr_style_job(
            make_cleaned_job, source_job_id="acme-corp-990003", title="Backend Engineer"
        )
        status_1 = repo.save_cleaned_job(
            db_session, job_initial, source_id=source_id, session_id=session_id
        )
        assert status_1 == "inserted"

        job_updated = _wwr_style_job(
            make_cleaned_job, source_job_id="acme-corp-990003", title="Senior Backend Engineer"
        )
        status_2 = repo.save_cleaned_job(
            db_session, job_updated, source_id=source_id, session_id=session_id
        )
        assert status_2 == "updated"

        job_row = db_session.execute(
            text("SELECT job_title FROM core.jobs WHERE source_job_id = 'acme-corp-990003'")
        ).first()
        assert job_row.job_title == "Senior Backend Engineer"


class TestClosingDateRoundTrip:
    """closing_date is new: no prior source ever wrote to
    core.jobs.closing_date before We Work Remotely. These confirm it
    actually persists and reads back correctly against real PostgreSQL,
    beyond what the mocked-Session unit tests in test_job_repository.py
    can prove.
    """

    def test_closing_date_persists_and_reads_back_on_insert(self, db_session, make_cleaned_job):
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "weworkremotely")
        session_id = repo.create_scraping_session(db_session, source_id)

        closing_date = datetime(2026, 12, 31, tzinfo=UTC)
        job = _wwr_style_job(
            make_cleaned_job, source_job_id="acme-corp-990004", closing_date=closing_date
        )
        repo.save_cleaned_job(db_session, job, source_id=source_id, session_id=session_id)

        row = db_session.execute(
            text("SELECT closing_date FROM core.jobs WHERE source_job_id = 'acme-corp-990004'")
        ).first()
        assert row.closing_date == closing_date.date()

    def test_none_closing_date_persists_as_null(self, db_session, make_cleaned_job):
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "weworkremotely")
        session_id = repo.create_scraping_session(db_session, source_id)

        job = _wwr_style_job(make_cleaned_job, source_job_id="acme-corp-990005", closing_date=None)
        repo.save_cleaned_job(db_session, job, source_id=source_id, session_id=session_id)

        row = db_session.execute(
            text("SELECT closing_date FROM core.jobs WHERE source_job_id = 'acme-corp-990005'")
        ).first()
        assert row.closing_date is None

    def test_closing_date_updates_even_when_other_content_unchanged(
        self, db_session, make_cleaned_job
    ):
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "weworkremotely")
        session_id = repo.create_scraping_session(db_session, source_id)

        # Relative, not hardcoded: posting_date is datetime.now(UTC), and
        # ck_jobs_closing_after_posting (canonical schema) rejects
        # closing_date < posting_date. A fixed date here became invalid
        # the moment it fell into the past (the original 2026-10-01
        # stopped satisfying the constraint on 2026-10-03).
        initial_closing = datetime.now(UTC) + timedelta(days=7)
        extended_closing = datetime.now(UTC) + timedelta(days=30)
        job = _wwr_style_job(
            make_cleaned_job,
            source_job_id="acme-corp-990006",
            closing_date=initial_closing,
        )
        status_1 = repo.save_cleaned_job(
            db_session, job, source_id=source_id, session_id=session_id
        )
        assert status_1 == "inserted"

        # Same job, only closing_date extended -- everything hashed stays
        # identical, so this must land on the "unchanged" branch, but
        # closing_date must still be refreshed in the database.
        job.closing_date = extended_closing
        status_2 = repo.save_cleaned_job(
            db_session, job, source_id=source_id, session_id=session_id
        )
        assert status_2 == "unchanged"

        row = db_session.execute(
            text("SELECT closing_date FROM core.jobs WHERE source_job_id = 'acme-corp-990006'")
        ).first()
        assert row.closing_date == extended_closing.date()


class TestWWRPipelineIntegration:
    def test_full_pipeline_run_with_mocked_fetch(self, db_session, monkeypatch):
        from unittest.mock import MagicMock

        from job_market_intel.validation import WWRValidationSettings

        pipeline = WWRPipeline(validation_settings=WWRValidationSettings(min_expected_jobs=1))
        mock_raw_data = [
            {
                "title": "DataCorp: Staff Data Engineer",
                "guid": "https://weworkremotely.com/remote-jobs/datacorp-880001",
                "link": "https://weworkremotely.com/remote-jobs/datacorp-880001",
                "region": "Anywhere in the World",
                "country": "",
                "state": "",
                "skills": "Python, SQL, Data",
                "category": "Programming",
                "type": "Full-Time",
                "description": "<p>Data engineering role at scale.</p>",
                "pubdate": "Sat, 01 Aug 2026 00:00:00 +0000",
                "expires_at": "Tue, 01 Sep 2026 00:00:00 +0000",
                "media_content_url": None,
            }
        ]

        monkeypatch.setattr(
            pipeline.client, "fetch_raw_jobs", MagicMock(return_value=mock_raw_data)
        )

        result = pipeline.run(store_db=True, session_override=db_session)

        assert result.raw_count == 1
        assert result.parsed_count == 1
        assert result.cleaned_count == 1
        assert result.validation_passed is True
        assert result.inserted_count == 1
        assert result.session_id is not None

        session_row = db_session.execute(
            text("SELECT status, jobs_new FROM ops.scraping_sessions WHERE session_id = :sid"),
            {"sid": result.session_id},
        ).first()
        assert session_row is not None
        assert session_row.status == "completed"
        assert session_row.jobs_new == 1

        # Confirm the WWR-specific transformations actually landed in the DB:
        # title split into company+job_title, closing_date populated from
        # expires_at, and salary correctly absent.
        job_row = db_session.execute(
            text(
                "SELECT j.job_title, j.closing_date, c.company_name, s.salary_disclosed "
                "FROM core.jobs j "
                "JOIN core.companies c ON c.company_id = j.company_id "
                "JOIN salary.job_salaries s ON s.job_id = j.job_id "
                "WHERE j.source_job_id = 'datacorp-880001'"
            )
        ).first()
        assert job_row is not None
        assert job_row.job_title == "Staff Data Engineer"
        assert job_row.company_name == "DataCorp"
        assert job_row.closing_date is not None
        assert job_row.salary_disclosed is False
