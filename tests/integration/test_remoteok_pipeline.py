"""Integration tests for RemoteOK Pipeline & JobRepository (Steps 9-13).

Tests live database storage, deduplication via content hashing, and pipeline
execution against a real, schema-applied PostgreSQL test instance.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os

import pytest
from sqlalchemy import text

from job_market_intel.cleaning.remoteok_cleaner import CleanedRemoteOKJob
from job_market_intel.db import engine as engine_module
from job_market_intel.db.job_repository import JobRepository
from job_market_intel.scrapers.remoteok.pipeline import RemoteOKPipeline
from seed.currencies import seed_currencies
from seed.sources import seed_sources

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

requires_live_db = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set; skipping live Postgres pipeline integration tests.",
)

pytestmark = requires_live_db


@pytest.fixture()
def db_session():
    """Provides a transactional session isolated per test."""
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL or ""
    engine_module.dispose_engine()
    engine = engine_module.get_engine()

    connection = engine.connect()
    trans = connection.begin()

    from sqlalchemy.orm import Session
    session = Session(bind=connection)

    # Seed required reference tables
    seed_currencies(connection)
    seed_sources(connection)

    yield session

    session.close()
    trans.rollback()
    connection.close()
    engine_module.dispose_engine()


class TestJobRepositoryIntegration:
    def _make_cleaned_job(self, source_job_id: str = "990001", title: str = "Lead Python Engineer") -> CleanedRemoteOKJob:
        return CleanedRemoteOKJob(
            source_job_id=source_job_id,
            job_title=title,
            company_name="Acme AI Corp",
            company_logo_url="https://acme.test/logo.png",
            tags=["python", "ai", "postgres"],
            location_cleaned="Remote - US",
            salary_min=140000,
            salary_max=180000,
            salary_disclosed=True,
            description_clean="We are looking for a Lead Python Engineer to build scalable data pipelines.",
            word_count=13,
            apply_url="https://acme.test/apply",
            original_url=f"https://remoteok.com/remote-jobs/{source_job_id}",
            posting_date=datetime.now(timezone.utc),
            data_quality_score=1.0,
            raw_payload={"id": source_job_id, "position": title},
        )

    def test_save_cleaned_job_inserts_new_record(self, db_session):
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        job = self._make_cleaned_job(source_job_id="990001")
        status = repo.save_cleaned_job(db_session, job, source_id=source_id, session_id=session_id)

        assert status == "inserted"

        # Verify insertion across core.jobs, core.companies, core.job_descriptions, salary.job_salaries
        job_row = db_session.execute(
            text("SELECT job_id, job_title, content_hash FROM core.jobs WHERE source_job_id = '990001'")
        ).first()
        assert job_row is not None
        assert job_row.job_title == "Lead Python Engineer"

        desc_row = db_session.execute(
            text("SELECT word_count FROM core.job_descriptions WHERE job_id = :job_id"),
            {"job_id": job_row.job_id},
        ).first()
        assert desc_row is not None
        assert desc_row.word_count == 13

        salary_row = db_session.execute(
            text("SELECT salary_min, salary_max FROM salary.job_salaries WHERE job_id = :job_id"),
            {"job_id": job_row.job_id},
        ).first()
        assert salary_row is not None
        assert int(salary_row.salary_min) == 140000
        assert int(salary_row.salary_max) == 180000

    def test_save_cleaned_job_detects_unchanged_record(self, db_session):
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        job = self._make_cleaned_job(source_job_id="990002")
        status_1 = repo.save_cleaned_job(db_session, job, source_id=source_id, session_id=session_id)
        assert status_1 == "inserted"

        # Save identical job again
        status_2 = repo.save_cleaned_job(db_session, job, source_id=source_id, session_id=session_id)
        assert status_2 == "unchanged"

    def test_save_cleaned_job_detects_updated_record(self, db_session):
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        job_initial = self._make_cleaned_job(source_job_id="990003", title="Python Engineer")
        status_1 = repo.save_cleaned_job(db_session, job_initial, source_id=source_id, session_id=session_id)
        assert status_1 == "inserted"

        # Update job with new title & salary
        job_updated = self._make_cleaned_job(source_job_id="990003", title="Senior Python Engineer")
        job_updated.salary_min = 160000
        status_2 = repo.save_cleaned_job(db_session, job_updated, source_id=source_id, session_id=session_id)
        assert status_2 == "updated"

        # Verify updated values in core.jobs & salary.job_salaries
        job_row = db_session.execute(
            text("SELECT job_id, job_title FROM core.jobs WHERE source_job_id = '990003'")
        ).first()
        assert job_row.job_title == "Senior Python Engineer"

        salary_row = db_session.execute(
            text("SELECT salary_min FROM salary.job_salaries WHERE job_id = :job_id"),
            {"job_id": job_row.job_id},
        ).first()
        assert int(salary_row.salary_min) == 160000


class TestRemoteOKPipelineIntegration:
    def test_full_pipeline_run_with_mocked_fetch(self, db_session, monkeypatch):
        from unittest.mock import MagicMock
        from job_market_intel.validation import RemoteOKValidationSettings

        pipeline = RemoteOKPipeline(
            validation_settings=RemoteOKValidationSettings(min_expected_jobs=1)
        )
        mock_raw_data = [
            {
                "id": "880001",
                "position": "Staff Data Engineer",
                "company": "DataCorp",
                "url": "https://remoteok.com/remote-jobs/880001",
                "location": "Worldwide",
                "salary_min": 150000,
                "salary_max": 200000,
                "tags": ["python", "sql", "data"],
                "description": "<p>Data engineering role at scale.</p>",
                "date": "2026-08-01T00:00:00+00:00",
            }
        ]

        monkeypatch.setattr(pipeline.client, "fetch_raw_jobs", MagicMock(return_value=mock_raw_data))

        result = pipeline.run(store_db=True, session_override=db_session)

        assert result.raw_count == 1
        assert result.parsed_count == 1
        assert result.cleaned_count == 1
        assert result.validation_passed is True
        assert result.inserted_count == 1
        assert result.session_id is not None

        # Verify session status in ops.scraping_sessions
        session_row = db_session.execute(
            text("SELECT status, jobs_new FROM ops.scraping_sessions WHERE session_id = :sid"),
            {"sid": result.session_id},
        ).first()
        assert session_row is not None
        assert session_row.status == "completed"
        assert session_row.jobs_new == 1
