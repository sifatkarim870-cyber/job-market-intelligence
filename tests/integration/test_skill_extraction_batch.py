"""Integration tests for the skill-extraction batch job (Step 26),
against a real, schema-applied PostgreSQL test instance.

Follows the same pattern as test_company_resolution_batch.py: seed real
ref.skills / core.jobs / core.job_descriptions rows (via
JobRepository.save_cleaned_job for jobs, so description_clean is
populated the same way real ingestion populates it), then confirm
run_skill_extraction_batch resolves matches correctly against real
bridge.job_skills rows -- not mocked SQL. Includes the real-DB version of
the R&D false-positive regression case already covered at the unit level
with synthetic data.

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
from job_market_intel.normalization.skill_extraction import (
    DEFAULT_EXTRACTED_BY,
    fetch_unscanned_jobs,
    run_skill_extraction_batch,
)

pytestmark = pytest.mark.requires_live_db


def _insert_skill_category(session: Session, category_name: str) -> int:
    category_id = session.execute(
        text(
            "INSERT INTO ref.skill_categories (category_name) VALUES (:name) "
            "RETURNING skill_category_id"
        ),
        {"name": category_name},
    ).scalar()
    assert category_id is not None
    return int(category_id)


def _insert_skill(
    session: Session,
    skill_name: str,
    category_id: int,
    aliases: list[str] | None = None,
) -> int:
    # Upsert, not plain INSERT: the live vocabulary may already contain
    # this skill (the local/CI ref.skills ships real seeded rows like
    # 'Python'/'PostgreSQL'), where a bare INSERT dies on
    # uq_skills_normalized_name. DO UPDATE returns the existing row's id,
    # so the assertions below hold either way; the category/alias
    # overwrite is reverted by the per-test rollback (see conftest.py).
    skill_id = session.execute(
        text(
            "INSERT INTO ref.skills "
            "(skill_name, normalized_skill_name, skill_category_id, aliases) "
            "VALUES (:skill_name, :normalized_skill_name, :category_id, :aliases) "
            "ON CONFLICT (normalized_skill_name) "
            "DO UPDATE SET skill_name = EXCLUDED.skill_name, "
            "skill_category_id = EXCLUDED.skill_category_id, "
            "aliases = EXCLUDED.aliases "
            "RETURNING skill_id"
        ),
        {
            "skill_name": skill_name,
            "normalized_skill_name": skill_name.lower(),
            "category_id": category_id,
            "aliases": aliases or [],
        },
    ).scalar()
    assert skill_id is not None
    return int(skill_id)


def _job(
    make_cleaned_job: Callable[..., CleanedJob],
    source_job_id: str,
    description_clean: str,
    **overrides: Any,
) -> CleanedJob:
    defaults: dict[str, Any] = {
        "company_name": "Acme Corp",
        "company_logo_url": None,
        "skills": [],
        "location_cleaned": "Remote",
        "salary_min": None,
        "salary_max": None,
        "salary_disclosed": False,
        "description_clean": description_clean,
        "word_count": len(description_clean.split()),
        "apply_url": None,
        "original_url": f"https://example.test/{source_job_id}",
        "posting_date": datetime.now(UTC),
        "data_quality_score": 1.0,
        "raw_payload": {"id": source_job_id},
    }
    defaults.update(overrides)
    return make_cleaned_job(source_job_id=source_job_id, job_title="Engineer", **defaults)


class TestSkillExtractionBatchAgainstLiveDB:
    def test_extracts_known_skills_from_description(self, db_session, make_cleaned_job) -> None:
        category_id = _insert_skill_category(db_session, "Test Programming Language")
        python_id = _insert_skill(db_session, "Python", category_id)
        postgres_id = _insert_skill(db_session, "PostgreSQL", category_id, aliases=["postgres"])

        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        job = _job(
            make_cleaned_job,
            "skill-extract-1",
            "We use Python and PostgreSQL daily on this team.",
        )
        repo.save_cleaned_job(db_session, job, source_id=source_id)
        db_session.flush()

        result = run_skill_extraction_batch(db_session)
        db_session.flush()

        assert result["jobs_scanned"] >= 1
        assert result["skill_associations_created"] >= 2

        matched_skill_ids = {
            row.skill_id
            for row in db_session.execute(
                text(
                    "SELECT bjs.skill_id FROM bridge.job_skills bjs "
                    "JOIN core.jobs j ON j.job_id = bjs.job_id "
                    "WHERE j.source_job_id = 'skill-extract-1' "
                    "AND bjs.extracted_by = :extracted_by"
                ),
                {"extracted_by": DEFAULT_EXTRACTED_BY},
            ).all()
        }
        assert matched_skill_ids == {python_id, postgres_id}

        row = db_session.execute(
            text(
                "SELECT requirement_type, confidence_score FROM bridge.job_skills bjs "
                "JOIN core.jobs j ON j.job_id = bjs.job_id "
                "WHERE j.source_job_id = 'skill-extract-1' LIMIT 1"
            )
        ).first()
        assert row.requirement_type == "required"
        assert float(row.confidence_score) == 1.0

    def test_rd_does_not_match_skill_r_against_real_db(self, db_session, make_cleaned_job) -> None:
        category_id = _insert_skill_category(db_session, "Test Programming Language R")
        r_skill_id = _insert_skill(db_session, "R", category_id)

        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        job = _job(
            make_cleaned_job,
            "skill-extract-rd",
            "Our R&D team is expanding and hiring across the org this year.",
        )
        repo.save_cleaned_job(db_session, job, source_id=source_id)
        db_session.flush()

        run_skill_extraction_batch(db_session)
        db_session.flush()

        matched = db_session.execute(
            text(
                "SELECT count(*) FROM bridge.job_skills bjs "
                "JOIN core.jobs j ON j.job_id = bjs.job_id "
                "WHERE j.source_job_id = 'skill-extract-rd' AND bjs.skill_id = :skill_id"
            ),
            {"skill_id": r_skill_id},
        ).scalar()
        assert matched == 0

    def test_rerun_is_idempotent(self, db_session, make_cleaned_job) -> None:
        category_id = _insert_skill_category(db_session, "Test Idempotent Category")
        _insert_skill(db_session, "Kubernetes", category_id)

        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        job = _job(make_cleaned_job, "skill-extract-idempotent", "We run everything on Kubernetes.")
        repo.save_cleaned_job(db_session, job, source_id=source_id)
        db_session.flush()

        first_result = run_skill_extraction_batch(db_session)
        db_session.flush()
        assert first_result["skill_associations_created"] == 1

        second_result = run_skill_extraction_batch(db_session)
        db_session.flush()
        # The job now has a job_skills row from this extractor, so
        # fetch_unscanned_jobs should no longer select it at all.
        assert second_result["jobs_scanned"] == 0
        assert second_result["skill_associations_created"] == 0

        count = db_session.execute(
            text(
                "SELECT count(*) FROM bridge.job_skills bjs "
                "JOIN core.jobs j ON j.job_id = bjs.job_id "
                "WHERE j.source_job_id = 'skill-extract-idempotent'"
            )
        ).scalar()
        assert count == 1

    def test_job_with_no_matches_is_rescanned_next_run(self, db_session, make_cleaned_job) -> None:
        # Documents the known limitation from the module docstring: a
        # job that was scanned and genuinely matched nothing looks
        # identical to an unscanned job (no bridge.job_skills row either
        # way), so it keeps getting re-selected. Not incorrect, just
        # wasteful -- this test exists so that behavior is visible and
        # intentional, not an accidental discovery later.
        category_id = _insert_skill_category(db_session, "Test No Match Category")
        _insert_skill(db_session, "Kubernetes", category_id)

        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        job = _job(
            make_cleaned_job,
            "skill-extract-nomatch",
            "This description mentions nothing from the vocabulary at all.",
        )
        repo.save_cleaned_job(db_session, job, source_id=source_id)
        db_session.flush()

        first_result = run_skill_extraction_batch(db_session)
        db_session.flush()
        assert first_result["skill_associations_created"] == 0

        still_unscanned = fetch_unscanned_jobs(db_session)
        assert any(j.job_id for j in still_unscanned if j.description_clean.startswith("This"))
