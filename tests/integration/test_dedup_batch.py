"""Integration tests for the cross-source duplicate-detection batch job
(Step 19), against a real, schema-applied PostgreSQL test instance.

Follows the same pattern as test_remoteok_pipeline.py /
test_weworkremotely_pipeline.py / test_remotive_pipeline.py: seed a
realistic CleanedJob via JobRepository.save_cleaned_job under one source,
then a near-identical one under a second source, and confirm
run_dedup_batch resolves them correctly against real core.jobs /
ref.sources / audit.change_log rows -- not mocked SQL.

The requires_live_db marker/skip behavior and the `db_session` fixture
are centralized in tests/integration/conftest.py.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.db.job_repository import JobRepository
from job_market_intel.normalization.config import DedupSettings
from job_market_intel.normalization.dedup import run_dedup_batch

pytestmark = pytest.mark.requires_live_db


def _job(
    make_cleaned_job: Callable[..., CleanedJob],
    source_job_id: str,
    title: str = "Senior Backend Engineer",
    company: str = "Acme Corp",
    posting_date: datetime | None = None,
    **overrides: Any,
) -> CleanedJob:
    defaults: dict[str, Any] = {
        "company_name": company,
        "company_logo_url": None,
        "skills": ["python"],
        "location_cleaned": "Remote",
        "salary_min": 120000,
        "salary_max": 160000,
        "salary_disclosed": True,
        "description_clean": "We are hiring a backend engineer.",
        "word_count": 6,
        "apply_url": None,
        "original_url": f"https://example.test/{source_job_id}",
        "posting_date": posting_date or datetime.now(UTC),
        "data_quality_score": 1.0,
        "raw_payload": {"id": source_job_id},
    }
    defaults.update(overrides)
    return make_cleaned_job(source_job_id=source_job_id, job_title=title, **defaults)


class TestDedupBatchAgainstLiveDB:
    def test_cross_source_duplicate_is_flagged_with_canonical(
        self, db_session, make_cleaned_job
    ) -> None:
        repo = JobRepository()

        remoteok_source_id = repo.get_source_id_by_code(db_session, "remoteok")
        wwr_source_id = repo.get_source_id_by_code(db_session, "weworkremotely")

        posting_date = datetime.now(UTC)

        job_a = _job(make_cleaned_job, "ro-1", posting_date=posting_date)
        job_b = _job(make_cleaned_job, "wwr-1", posting_date=posting_date)

        repo.save_cleaned_job(db_session, job_a, source_id=remoteok_source_id)
        repo.save_cleaned_job(db_session, job_b, source_id=wwr_source_id)
        db_session.flush()

        # remoteok has the higher trust_score per seed/sources.py (0.75
        # vs weworkremotely's 0.75 -- actually equal; use an explicit
        # override below via direct SQL so this test doesn't silently
        # depend on seed data staying exactly as-is).
        db_session.execute(
            text("UPDATE ref.sources SET trust_score = 0.90 WHERE source_id = :sid"),
            {"sid": remoteok_source_id},
        )
        db_session.execute(
            text("UPDATE ref.sources SET trust_score = 0.60 WHERE source_id = :sid"),
            {"sid": wwr_source_id},
        )
        db_session.flush()

        result = run_dedup_batch(db_session, settings=DedupSettings(posting_date_window_days=3))
        db_session.flush()

        assert result["candidates_scanned"] == 2
        assert result["matches_found"] == 1
        assert result["matches_applied"] == 1

        rows = db_session.execute(
            text(
                "SELECT j.source_id, j.is_duplicate_of FROM core.jobs j "
                "WHERE j.source_id IN (:a, :b) ORDER BY j.source_id"
            ),
            {"a": remoteok_source_id, "b": wwr_source_id},
        ).all()
        by_source = {row.source_id: row.is_duplicate_of for row in rows}

        # remoteok (higher trust_score) stays canonical: is_duplicate_of IS NULL.
        assert by_source[remoteok_source_id] is None
        # weworkremotely gets flagged, pointing at remoteok's job_id.
        assert by_source[wwr_source_id] is not None

        audit_rows = db_session.execute(
            text(
                "SELECT table_name, operation FROM audit.change_log "
                "WHERE table_name = 'core.jobs' AND operation = 'update'"
            )
        ).all()
        assert len(audit_rows) == 1

    def test_no_match_for_genuinely_different_jobs(self, db_session, make_cleaned_job) -> None:
        repo = JobRepository()
        remoteok_source_id = repo.get_source_id_by_code(db_session, "remoteok")
        wwr_source_id = repo.get_source_id_by_code(db_session, "weworkremotely")

        job_a = _job(make_cleaned_job, "ro-2", title="Frontend Engineer", company="Acme Corp")
        job_b = _job(make_cleaned_job, "wwr-2", title="Data Scientist", company="Widgets Inc")

        repo.save_cleaned_job(db_session, job_a, source_id=remoteok_source_id)
        repo.save_cleaned_job(db_session, job_b, source_id=wwr_source_id)
        db_session.flush()

        result = run_dedup_batch(db_session)
        db_session.flush()

        assert result["matches_found"] == 0
        assert result["matches_applied"] == 0

    def test_rerun_does_not_reprocess_already_flagged_jobs(
        self, db_session, make_cleaned_job
    ) -> None:
        repo = JobRepository()
        remoteok_source_id = repo.get_source_id_by_code(db_session, "remoteok")
        wwr_source_id = repo.get_source_id_by_code(db_session, "weworkremotely")

        posting_date = datetime.now(UTC)
        job_a = _job(make_cleaned_job, "ro-3", posting_date=posting_date)
        job_b = _job(make_cleaned_job, "wwr-3", posting_date=posting_date)

        repo.save_cleaned_job(db_session, job_a, source_id=remoteok_source_id)
        repo.save_cleaned_job(db_session, job_b, source_id=wwr_source_id)
        db_session.flush()

        first_result = run_dedup_batch(db_session)
        db_session.flush()
        assert first_result["matches_applied"] == 1

        second_result = run_dedup_batch(db_session)
        db_session.flush()
        # The canonical job (remoteok, higher trust_score) legitimately
        # keeps is_duplicate_of = NULL forever -- it's not a duplicate,
        # it's what other rows point at -- so it still shows up as a
        # candidate on the second run. What must NOT happen is a new
        # match/apply against it, since its one-time duplicate partner
        # is now excluded by the is_duplicate_of IS NULL filter.
        assert second_result["candidates_scanned"] == 1
        assert second_result["matches_found"] == 0
        assert second_result["matches_applied"] == 0
