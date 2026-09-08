"""Integration tests for the company-alias candidate-generation batch job
(Step 25), against a real, schema-applied PostgreSQL test instance.

Follows the same pattern as test_dedup_batch.py: seed real core.companies
(and, where job_count matters, real core.jobs via
JobRepository.save_cleaned_job) rows, then confirm
run_company_resolution_batch resolves candidates correctly against real
core.companies / core.company_aliases / audit.change_log rows -- not
mocked SQL.

The requires_live_db marker/skip behavior and the `db_session` fixture
are centralized in tests/integration/conftest.py.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.db.job_repository import JobRepository
from job_market_intel.normalization.company_resolution import (
    reject_alias_candidates,
    run_company_resolution_batch,
)
from job_market_intel.normalization.config import CompanyResolutionSettings

pytestmark = pytest.mark.requires_live_db


def _insert_company(session: Session, company_name: str) -> int:
    """Directly inserts a core.companies row -- bypassing
    get_or_create_company on purpose, since this test suite is
    exercising company_resolution against companies as data, not
    exercising the ingestion write path (that's covered elsewhere).
    """
    company_id = session.execute(
        text(
            "INSERT INTO core.companies (company_name, normalized_name) "
            "VALUES (:company_name, :normalized_name) RETURNING company_id"
        ),
        {"company_name": company_name, "normalized_name": company_name.lower()},
    ).scalar()
    assert company_id is not None
    return int(company_id)


def _job(
    make_cleaned_job: Callable[..., CleanedJob],
    source_job_id: str,
    company: str,
    **overrides: Any,
) -> CleanedJob:
    defaults: dict[str, Any] = {
        "company_name": company,
        "company_logo_url": None,
        "skills": ["python"],
        "location_cleaned": "Remote",
        "salary_min": None,
        "salary_max": None,
        "salary_disclosed": False,
        "description_clean": "A job.",
        "word_count": 2,
        "apply_url": None,
        "original_url": f"https://example.test/{source_job_id}",
        "posting_date": datetime.now(UTC),
        "data_quality_score": 1.0,
        "raw_payload": {"id": source_job_id},
    }
    defaults.update(overrides)
    return make_cleaned_job(source_job_id=source_job_id, job_title="Engineer", **defaults)


class TestCompanyResolutionBatchAgainstLiveDB:
    def test_finds_candidate_for_similar_company_names(self, db_session) -> None:
        dexterra_id = _insert_company(db_session, "Dexterra")
        dexterra_group_id = _insert_company(db_session, "Dexterra Group")
        db_session.flush()

        result = run_company_resolution_batch(
            db_session, settings=CompanyResolutionSettings(similarity_threshold=0.5)
        )
        db_session.flush()

        assert result["candidates_found"] == 1
        assert result["candidates_applied"] == 1

        alias_row = db_session.execute(
            text(
                "SELECT company_id, raw_name, match_confidence FROM core.company_aliases "
                "WHERE source_id IS NULL"
            )
        ).first()
        assert alias_row is not None
        # No jobs on either company -> tiebreak is shorter normalized_name:
        # "Dexterra" (8 chars) beats "Dexterra Group" (14 chars).
        assert alias_row.company_id == dexterra_id
        assert alias_row.raw_name == "Dexterra Group"
        assert alias_row.match_confidence is not None

        # Firm "no auto-merge" decision, confirmed against real rows:
        # neither company's is_verified flipped, and the alias company_id
        # (dexterra_group_id) never appears as a canonical elsewhere.
        companies = db_session.execute(
            text("SELECT company_id, is_verified FROM core.companies WHERE company_id IN (:a, :b)"),
            {"a": dexterra_id, "b": dexterra_group_id},
        ).all()
        assert all(row.is_verified is False for row in companies)

    def test_no_candidate_for_dissimilar_company_names(self, db_session) -> None:
        _insert_company(db_session, "Totally Unrelated Corp")
        _insert_company(db_session, "SpaceX")
        db_session.flush()

        result = run_company_resolution_batch(db_session)
        db_session.flush()

        assert result["candidates_found"] == 0
        assert result["candidates_applied"] == 0

    def test_no_false_positive_for_unrelated_companies_sharing_a_suffix_word(
        self, db_session
    ) -> None:
        # Regression case: exactly this pair (real company_names from the
        # live database) matched at similarity=0.55 before suffix
        # stripping existed, purely because both end in "Corporation".
        # Suffix stripping must exclude it now.
        _insert_company(db_session, "Zegogo Corporation")
        _insert_company(db_session, "YT Corporation")
        db_session.flush()

        result = run_company_resolution_batch(
            db_session, settings=CompanyResolutionSettings(similarity_threshold=0.5)
        )
        db_session.flush()

        assert result["candidates_found"] == 0
        assert result["candidates_applied"] == 0

    def test_company_with_more_jobs_is_canonical(self, db_session, make_cleaned_job) -> None:
        repo = JobRepository()
        remoteok_source_id = repo.get_source_id_by_code(db_session, "remoteok")

        # "Acme" gets 2 jobs, "Acme Corp" gets 0 -- despite being the
        # shorter name, "Acme" should NOT automatically win; the company
        # with more real postings should be canonical.
        job_a = _job(make_cleaned_job, "acme-1", company="Acme Corp")
        job_b = _job(make_cleaned_job, "acme-2", company="Acme Corp")
        repo.save_cleaned_job(db_session, job_a, source_id=remoteok_source_id)
        repo.save_cleaned_job(db_session, job_b, source_id=remoteok_source_id)
        _insert_company(db_session, "Acme")
        db_session.flush()

        result = run_company_resolution_batch(
            db_session, settings=CompanyResolutionSettings(similarity_threshold=0.5)
        )
        db_session.flush()

        assert result["candidates_applied"] == 1

        alias_row = db_session.execute(
            text(
                "SELECT c.company_name AS canonical_name, ca.raw_name FROM core.company_aliases ca "
                "JOIN core.companies c ON c.company_id = ca.company_id "
                "WHERE ca.source_id IS NULL"
            )
        ).first()
        assert alias_row is not None
        assert alias_row.canonical_name == "Acme Corp"
        assert alias_row.raw_name == "Acme"

    def test_rerun_does_not_reinsert_already_recorded_candidate(self, db_session) -> None:
        _insert_company(db_session, "Dexterra")
        _insert_company(db_session, "Dexterra Group")
        db_session.flush()

        settings = CompanyResolutionSettings(similarity_threshold=0.5)

        first_result = run_company_resolution_batch(db_session, settings=settings)
        db_session.flush()
        assert first_result["candidates_applied"] == 1

        second_result = run_company_resolution_batch(db_session, settings=settings)
        db_session.flush()
        assert second_result["candidates_found"] == 0
        assert second_result["candidates_applied"] == 0

        alias_rows = db_session.execute(
            text("SELECT count(*) FROM core.company_aliases WHERE source_id IS NULL")
        ).scalar()
        assert alias_rows == 1

    def test_rejected_candidate_is_not_reproposed_on_next_batch_run(self, db_session) -> None:
        # Regression test for the real bug hit during first real
        # review-script usage: reject a candidate, then confirm a
        # subsequent batch run does NOT bring it back. Before
        # reject_alias_candidates logged to audit.change_log, this exact
        # sequence re-proposed the identical pair every time (the "I
        # don't know what I did" session).
        dexterra_id = _insert_company(db_session, "Dexterra")
        _insert_company(db_session, "Dexterra Group")
        db_session.flush()

        settings = CompanyResolutionSettings(similarity_threshold=0.5)

        first_result = run_company_resolution_batch(db_session, settings=settings)
        db_session.flush()
        assert first_result["candidates_applied"] == 1

        deleted = reject_alias_candidates(
            db_session,
            canonical_company_id=dexterra_id,
            canonical_company_name="Dexterra",
            alias_raw_names=["Dexterra Group"],
        )
        db_session.flush()
        assert deleted == 1

        second_result = run_company_resolution_batch(db_session, settings=settings)
        db_session.flush()

        assert second_result["candidates_found"] == 0
        assert second_result["candidates_applied"] == 0

        alias_rows = db_session.execute(
            text("SELECT count(*) FROM core.company_aliases WHERE source_id IS NULL")
        ).scalar()
        assert alias_rows == 0
