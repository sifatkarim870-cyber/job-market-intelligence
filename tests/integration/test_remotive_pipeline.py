"""Integration tests for Remotive Pipeline & JobRepository (Step 18).

Mirrors ``integration/test_remoteok_pipeline.py``'s structure and
rationale exactly — see that module's docstring. The two integration
tests here (JobRepository storage/dedup, full pipeline run) intentionally
do NOT duplicate every JobRepository scenario RemoteOK's/WWR's
integration suites already cover (insert/unchanged/updated) — since
``db/job_repository.py`` is fully source-agnostic (confirmed during the
Step 18 investigation), one save + one full-pipeline-run test here is
enough to confirm Remotive's own field mapping reaches the database
correctly; it is not re-proving JobRepository's own dedup logic, which the
other two sources' integration suites already do thoroughly.

The requires_live_db marker/skip behavior and the `db_session` fixture
are both centralized in tests/integration/conftest.py.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.db.job_repository import JobRepository
from job_market_intel.scrapers.remotive.pipeline import RemotivePipeline

pytestmark = pytest.mark.requires_live_db


def _remotive_style_job(
    make_cleaned_job: Callable[..., CleanedJob],
    source_job_id: str = "770001",
    title: str = "Lead Backend Engineer",
    **overrides: Any,
) -> CleanedJob:
    """A realistic, fully-populated "Remotive-shaped" CleanedJob.

    Same "small local preset layered on the shared bare-bones factory"
    pattern ``test_remoteok_pipeline.py``'s own docstring establishes —
    see that module for the rationale. Note ``closing_date`` is not set
    here (stays ``None``): Remotive has no posting-expiration field.
    """
    defaults: dict[str, Any] = {
        "company_name": "Globex Remote Inc",
        "company_logo_url": "https://globex.test/logo.png",
        "skills": ["python", "fastapi", "postgres"],
        "location_cleaned": "USA",
        "salary_min": 130000,
        "salary_max": 170000,
        "salary_disclosed": True,
        "description_clean": (
            "We are looking for a Lead Backend Engineer to build our core platform."
        ),
        "word_count": 12,
        "apply_url": f"https://remotive.com/remote-jobs/{source_job_id}",
        "original_url": f"https://remotive.com/remote-jobs/{source_job_id}",
        "posting_date": datetime.now(UTC),
        "data_quality_score": 1.0,
        "raw_payload": {"id": source_job_id, "title": title},
    }
    defaults.update(overrides)
    return make_cleaned_job(source_job_id=source_job_id, job_title=title, **defaults)


class TestJobRepositoryIntegrationRemotive:
    def test_save_cleaned_job_inserts_new_record(self, db_session, make_cleaned_job):
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remotive")
        session_id = repo.create_scraping_session(db_session, source_id)

        job = _remotive_style_job(make_cleaned_job, source_job_id="770001")
        status = repo.save_cleaned_job(db_session, job, source_id=source_id, session_id=session_id)

        assert status == "inserted"

        job_row = db_session.execute(
            text(
                "SELECT job_id, job_title, content_hash FROM core.jobs "
                "WHERE source_job_id = '770001'"
            )
        ).first()
        assert job_row is not None
        assert job_row.job_title == "Lead Backend Engineer"

        desc_row = db_session.execute(
            text("SELECT word_count FROM core.job_descriptions WHERE job_id = :job_id"),
            {"job_id": job_row.job_id},
        ).first()
        assert desc_row is not None
        assert desc_row.word_count == 12

        salary_row = db_session.execute(
            text("SELECT salary_min, salary_max FROM salary.job_salaries WHERE job_id = :job_id"),
            {"job_id": job_row.job_id},
        ).first()
        assert salary_row is not None
        assert int(salary_row.salary_min) == 130000
        assert int(salary_row.salary_max) == 170000

    def test_save_cleaned_job_detects_unchanged_record(self, db_session, make_cleaned_job):
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remotive")
        session_id = repo.create_scraping_session(db_session, source_id)

        job = _remotive_style_job(make_cleaned_job, source_job_id="770002")
        status_1 = repo.save_cleaned_job(
            db_session, job, source_id=source_id, session_id=session_id
        )
        assert status_1 == "inserted"

        status_2 = repo.save_cleaned_job(
            db_session, job, source_id=source_id, session_id=session_id
        )
        assert status_2 == "unchanged"


class TestRemotivePipelineIntegration:
    def test_full_pipeline_run_with_mocked_fetch(self, db_session, monkeypatch):

        from job_market_intel.validation import RemotiveValidationSettings

        pipeline = RemotivePipeline(
            validation_settings=RemotiveValidationSettings(min_expected_jobs=1)
        )
        mock_raw_response = {
            "job-count": 1,
            "jobs": [
                {
                    "id": 660001,
                    "title": "Staff Platform Engineer",
                    "company_name": "PlatformCo",
                    "company_logo": "https://platformco.test/logo.png",
                    "category": "Software Development",
                    "job_type": "full_time",
                    "url": "https://remotive.com/remote-jobs/660001",
                    "candidate_required_location": "Worldwide",
                    "salary": "$150,000 - $200,000",
                    "tags": ["python", "kubernetes", "platform"],
                    "description": "<p>Platform engineering at scale.</p>",
                    "publication_date": "2026-08-01T00:00:00",
                }
            ],
        }

        monkeypatch.setattr(
            "job_market_intel.scrapers.remotive.client.fetch_json",
            lambda *args, **kwargs: mock_raw_response,
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

        # Confirm the parsed salary range actually made it to the database.
        job_row = db_session.execute(
            text("SELECT job_id FROM core.jobs WHERE source_job_id = '660001'")
        ).first()
        assert job_row is not None
        salary_row = db_session.execute(
            text("SELECT salary_min, salary_max FROM salary.job_salaries WHERE job_id = :job_id"),
            {"job_id": job_row.job_id},
        ).first()
        assert int(salary_row.salary_min) == 150000
        assert int(salary_row.salary_max) == 200000
