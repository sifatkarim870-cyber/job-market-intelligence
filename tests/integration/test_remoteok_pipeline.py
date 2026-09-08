"""Integration tests for RemoteOK Pipeline & JobRepository (Steps 9-13).

Tests live database storage, deduplication via content hashing, and pipeline
execution against a real, schema-applied PostgreSQL test instance.

The requires_live_db marker/skip behavior and the `db_session` fixture
(a transactional, pre-seeded ORM Session) are both centralized in
tests/integration/conftest.py — see that file's module docstring for why.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.db.job_repository import JobRepository
from job_market_intel.scrapers.remoteok.pipeline import RemoteOKPipeline

pytestmark = pytest.mark.requires_live_db


def _remoteok_style_job(
    make_cleaned_job: Callable[..., CleanedJob],
    source_job_id: str = "990001",
    title: str = "Lead Python Engineer",
    **overrides: Any,
) -> CleanedJob:
    """A realistic, fully-populated "RemoteOK-shaped" CleanedJob, built on
    top of the shared `make_cleaned_job` fixture (see tests/conftest.py)
    rather than reimplementing a second CleanedJob factory here.

    This is the pattern future sources' integration tests should follow:
    a small, local "realistic preset" layered on the shared bare-bones
    factory, not a standalone duplicate of it.
    """
    defaults: dict[str, Any] = {
        "company_name": "Acme AI Corp",
        "company_logo_url": "https://acme.test/logo.png",
        "skills": ["python", "ai", "postgres"],
        "location_cleaned": "Remote - US",
        "salary_min": 140000,
        "salary_max": 180000,
        "salary_disclosed": True,
        "description_clean": (
            "We are looking for a Lead Python Engineer to build scalable data pipelines."
        ),
        "word_count": 13,
        "apply_url": "https://acme.test/apply",
        "original_url": f"https://remoteok.com/remote-jobs/{source_job_id}",
        "posting_date": datetime.now(UTC),
        "data_quality_score": 1.0,
        "raw_payload": {"id": source_job_id, "position": title},
    }
    defaults.update(overrides)
    return make_cleaned_job(source_job_id=source_job_id, job_title=title, **defaults)


class TestJobRepositoryIntegration:
    def test_save_cleaned_job_inserts_new_record(self, db_session, make_cleaned_job):
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        job = _remoteok_style_job(make_cleaned_job, source_job_id="990001")
        status = repo.save_cleaned_job(db_session, job, source_id=source_id, session_id=session_id)

        assert status == "inserted"

        # Verify insertion across core.jobs, core.companies, core.job_descriptions,
        # salary.job_salaries
        job_row = db_session.execute(
            text(
                "SELECT job_id, job_title, content_hash FROM core.jobs "
                "WHERE source_job_id = '990001'"
            )
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
            text(
                "SELECT salary_min, salary_max, normalized_annual_min_usd, "
                "normalized_annual_max_usd FROM salary.job_salaries WHERE job_id = :job_id"
            ),
            {"job_id": job_row.job_id},
        ).first()
        assert salary_row is not None
        assert int(salary_row.salary_min) == 140000
        assert int(salary_row.salary_max) == 180000
        # Step 27: normalized_annual_*_usd computed via
        # normalize_annual_salary, not left NULL. USD/yearly today -> an
        # identity op numerically, but exercised as a real function call
        # against the real DB column, not asserted against a mock.
        assert float(salary_row.normalized_annual_min_usd) == 140000.0
        assert float(salary_row.normalized_annual_max_usd) == 180000.0

        # Step 27: every new job also gets a Day 1 salary.salary_history
        # row on insert, matching the salary it shipped with -- confirmed
        # against the real DB, since no prior integration test touched
        # salary.salary_history at all.
        history_rows = db_session.execute(
            text(
                "SELECT salary_min, salary_max FROM salary.salary_history "
                "WHERE job_id = :job_id ORDER BY observed_at"
            ),
            {"job_id": job_row.job_id},
        ).all()
        assert len(history_rows) == 1
        assert int(history_rows[0].salary_min) == 140000
        assert int(history_rows[0].salary_max) == 180000
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        job = _remoteok_style_job(make_cleaned_job, source_job_id="990002")
        status_1 = repo.save_cleaned_job(
            db_session, job, source_id=source_id, session_id=session_id
        )
        assert status_1 == "inserted"

        # Save identical job again
        status_2 = repo.save_cleaned_job(
            db_session, job, source_id=source_id, session_id=session_id
        )
        assert status_2 == "unchanged"

    def test_save_cleaned_job_detects_updated_record(self, db_session, make_cleaned_job):
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        job_initial = _remoteok_style_job(
            make_cleaned_job, source_job_id="990003", title="Python Engineer"
        )
        status_1 = repo.save_cleaned_job(
            db_session, job_initial, source_id=source_id, session_id=session_id
        )
        assert status_1 == "inserted"

        # Update job with new title & salary
        job_updated = _remoteok_style_job(
            make_cleaned_job, source_job_id="990003", title="Senior Python Engineer"
        )
        job_updated.salary_min = 160000
        status_2 = repo.save_cleaned_job(
            db_session, job_updated, source_id=source_id, session_id=session_id
        )
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

        # Step 27: a substantive salary change (140000/180000 -> 160000/180000,
        # both old and new fully disclosed) appends a second real row to
        # salary.salary_history rather than only overwriting job_salaries.
        history_rows = db_session.execute(
            text(
                "SELECT salary_min, salary_max FROM salary.salary_history "
                "WHERE job_id = :job_id ORDER BY observed_at"
            ),
            {"job_id": job_row.job_id},
        ).all()
        assert len(history_rows) == 2
        assert int(history_rows[0].salary_min) == 140000  # Day 1 row, from insert
        assert int(history_rows[1].salary_min) == 160000  # appended on this update

    def test_save_cleaned_job_disclosure_toggle_does_not_append_history(
        self, db_session, make_cleaned_job
    ) -> None:
        """A re-scrape where salary flips from disclosed -> undisclosed (or
        vice versa) is not a "the salary changed" event in the sense
        salary.salary_history exists to capture -- confirmed against the
        real DB, mirroring the mocked-session unit tests in
        tests/unit/db/test_job_repository.py::TestSalaryStandardization.
        """
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        job_initial = _remoteok_style_job(
            make_cleaned_job, source_job_id="990004", title="Data Analyst"
        )
        status_1 = repo.save_cleaned_job(
            db_session, job_initial, source_id=source_id, session_id=session_id
        )
        assert status_1 == "inserted"

        job_updated = _remoteok_style_job(
            make_cleaned_job,
            source_job_id="990004",
            title="Senior Data Analyst",  # forces a content_hash change
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
        )
        status_2 = repo.save_cleaned_job(
            db_session, job_updated, source_id=source_id, session_id=session_id
        )
        assert status_2 == "updated"

        job_row = db_session.execute(
            text("SELECT job_id FROM core.jobs WHERE source_job_id = '990004'")
        ).first()
        salary_row = db_session.execute(
            text(
                "SELECT salary_min, salary_max, salary_disclosed "
                "FROM salary.job_salaries WHERE job_id = :job_id"
            ),
            {"job_id": job_row.job_id},
        ).first()
        assert salary_row.salary_min is None
        assert salary_row.salary_disclosed is False

        history_rows = db_session.execute(
            text("SELECT salary_min FROM salary.salary_history WHERE job_id = :job_id"),
            {"job_id": job_row.job_id},
        ).all()
        # Only the Day 1 insert row -- the toggle to undisclosed did NOT
        # append a second row.
        assert len(history_rows) == 1


class TestGeographicResolutionIntegration:
    """Step 28, against a real schema-applied, seeded Postgres instance
    (ref.countries/regions/cities/remote_work_types are seeded by
    seed/run_all.py -- see tests/integration/conftest.py for how
    db_session gets a seeded database). Confirms the resolver's SQL is
    actually valid against real reference data, not just mocked-session
    behavior (that's tests/unit/normalization/test_geographic_resolution.py's
    job) -- and confirms save_cleaned_job actually persists location_id
    end-to-end.
    """

    def test_country_level_match_via_alias_map(self, db_session, make_cleaned_job) -> None:
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        # "Remote - US" is _remoteok_style_job's own default location text --
        # exercises the real prefix-strip + "us" -> "United States" alias.
        job = _remoteok_style_job(make_cleaned_job, source_job_id="990101")
        status = repo.save_cleaned_job(db_session, job, source_id=source_id, session_id=session_id)
        assert status == "inserted"

        row = db_session.execute(
            text(
                "SELECT l.country_id, l.city_id, l.region_id, l.is_global_remote, "
                "rwt.code AS remote_work_type_code, co.country_name "
                "FROM core.jobs j "
                "JOIN ref.locations l ON l.location_id = j.location_id "
                "JOIN ref.remote_work_types rwt ON rwt.remote_work_type_id = l.remote_work_type_id "
                "JOIN ref.countries co ON co.country_id = l.country_id "
                "WHERE j.source_job_id = '990101'"
            )
        ).first()
        assert row is not None
        assert row.country_name == "United States"
        assert row.city_id is None
        assert row.remote_work_type_code == "remote_country"
        assert row.is_global_remote is False

        alias_row = db_session.execute(
            text(
                "SELECT match_method FROM core.location_aliases "
                "WHERE raw_location_text = 'Remote - US' AND source_id = :source_id"
            ),
            {"source_id": source_id},
        ).first()
        assert alias_row is not None
        assert alias_row.match_method == "country_exact"

    def test_city_level_match(self, db_session, make_cleaned_job) -> None:
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        job = _remoteok_style_job(
            make_cleaned_job, source_job_id="990102", location_cleaned="Remote - Austin"
        )
        repo.save_cleaned_job(db_session, job, source_id=source_id, session_id=session_id)

        row = db_session.execute(
            text(
                "SELECT ci.city_name, rwt.code AS remote_work_type_code "
                "FROM core.jobs j "
                "JOIN ref.locations l ON l.location_id = j.location_id "
                "JOIN ref.remote_work_types rwt ON rwt.remote_work_type_id = l.remote_work_type_id "
                "JOIN ref.cities ci ON ci.city_id = l.city_id "
                "WHERE j.source_job_id = '990102'"
            )
        ).first()
        assert row is not None
        assert row.city_name == "Austin"
        assert row.remote_work_type_code == "remote_city"

    def test_explicit_global_assertion(self, db_session, make_cleaned_job) -> None:
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        job = _remoteok_style_job(
            make_cleaned_job, source_job_id="990103", location_cleaned="Worldwide"
        )
        repo.save_cleaned_job(db_session, job, source_id=source_id, session_id=session_id)

        row = db_session.execute(
            text(
                "SELECT l.is_global_remote, rwt.code AS remote_work_type_code, "
                "l.city_id, l.region_id, l.country_id "
                "FROM core.jobs j "
                "JOIN ref.locations l ON l.location_id = j.location_id "
                "JOIN ref.remote_work_types rwt ON rwt.remote_work_type_id = l.remote_work_type_id "
                "WHERE j.source_job_id = '990103'"
            )
        ).first()
        assert row is not None
        assert row.remote_work_type_code == "remote_global"
        assert row.is_global_remote is True
        assert row.city_id is None and row.region_id is None and row.country_id is None

    def test_unmatched_text_falls_back_to_global_but_stays_distinguishable(
        self, db_session, make_cleaned_job
    ) -> None:
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        job = _remoteok_style_job(
            make_cleaned_job, source_job_id="990104", location_cleaned="Narnia"
        )
        repo.save_cleaned_job(db_session, job, source_id=source_id, session_id=session_id)

        row = db_session.execute(
            text(
                "SELECT l.is_global_remote, rwt.code AS remote_work_type_code "
                "FROM core.jobs j "
                "JOIN ref.locations l ON l.location_id = j.location_id "
                "JOIN ref.remote_work_types rwt ON rwt.remote_work_type_id = l.remote_work_type_id "
                "WHERE j.source_job_id = '990104'"
            )
        ).first()
        assert row is not None
        assert row.remote_work_type_code == "remote_global"
        # False here, not True -- distinguishes "we couldn't parse this"
        # from an actual "Worldwide" assertion (see previous test).
        assert row.is_global_remote is False

        alias_row = db_session.execute(
            text(
                "SELECT match_method FROM core.location_aliases "
                "WHERE raw_location_text = 'Narnia' AND source_id = :source_id"
            ),
            {"source_id": source_id},
        ).first()
        assert alias_row.match_method == "fallback_unmatched"

    def test_multi_segment_prefers_most_specific_match(self, db_session, make_cleaned_job) -> None:
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        job = _remoteok_style_job(
            make_cleaned_job,
            source_job_id="990105",
            location_cleaned="Anywhere in the World; France; Berlin",
        )
        repo.save_cleaned_job(db_session, job, source_id=source_id, session_id=session_id)

        row = db_session.execute(
            text(
                "SELECT ci.city_name FROM core.jobs j "
                "JOIN ref.locations l ON l.location_id = j.location_id "
                "JOIN ref.cities ci ON ci.city_id = l.city_id "
                "WHERE j.source_job_id = '990105'"
            )
        ).first()
        # City (Berlin) wins over country (France) and the global phrase --
        # see Decision #4 / the module docstring's "Matching strategy".
        assert row is not None
        assert row.city_name == "Berlin"

    def test_repeated_raw_string_reuses_cached_alias_and_location(
        self, db_session, make_cleaned_job
    ) -> None:
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        job_a = _remoteok_style_job(
            make_cleaned_job, source_job_id="990106", location_cleaned="Remote - Seattle"
        )
        job_b = _remoteok_style_job(
            make_cleaned_job, source_job_id="990107", location_cleaned="Remote - Seattle"
        )
        repo.save_cleaned_job(db_session, job_a, source_id=source_id, session_id=session_id)
        repo.save_cleaned_job(db_session, job_b, source_id=source_id, session_id=session_id)

        alias_rows = db_session.execute(
            text(
                "SELECT location_id FROM core.location_aliases "
                "WHERE raw_location_text = 'Remote - Seattle' AND source_id = :source_id"
            ),
            {"source_id": source_id},
        ).all()
        # Exactly one cache row for this (raw_text, source_id) pair, not
        # one per job -- the second save hit the cache, never re-ran the
        # segment-match logic.
        assert len(alias_rows) == 1

        location_ids = db_session.execute(
            text(
                "SELECT DISTINCT location_id FROM core.jobs "
                "WHERE source_job_id IN ('990106', '990107')"
            )
        ).all()
        # Both jobs point at the SAME ref.locations row.
        assert len(location_ids) == 1

    def test_unmatched_locations_collapse_onto_one_reusable_row(
        self, db_session, make_cleaned_job
    ) -> None:
        """Regression guard for the NULL-vs-NULL dedup fix in
        get_or_create_location (IS NOT DISTINCT FROM, not "="): two
        DIFFERENT raw strings that both fall back to unmatched-global
        must still collapse onto the SAME ref.locations row (all three of
        city/region/country_id NULL), not accumulate a duplicate row per
        distinct unparseable string.
        """
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        job_a = _remoteok_style_job(
            make_cleaned_job, source_job_id="990108", location_cleaned="Narnia"
        )
        job_b = _remoteok_style_job(
            make_cleaned_job, source_job_id="990109", location_cleaned="Atlantis"
        )
        repo.save_cleaned_job(db_session, job_a, source_id=source_id, session_id=session_id)
        repo.save_cleaned_job(db_session, job_b, source_id=source_id, session_id=session_id)

        location_ids = db_session.execute(
            text(
                "SELECT DISTINCT location_id FROM core.jobs "
                "WHERE source_job_id IN ('990108', '990109')"
            )
        ).all()
        assert len(location_ids) == 1

        # And core.location_aliases still recorded BOTH raw strings
        # separately, even though they share one ref.locations row --
        # the cache/audit trail must not lose either original string.
        alias_count = db_session.execute(
            text(
                "SELECT count(*) FROM core.location_aliases "
                "WHERE raw_location_text IN ('Narnia', 'Atlantis') AND source_id = :source_id"
            ),
            {"source_id": source_id},
        ).scalar()
        assert alias_count == 2


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

        # Verify session status in ops.scraping_sessions
        session_row = db_session.execute(
            text("SELECT status, jobs_new FROM ops.scraping_sessions WHERE session_id = :sid"),
            {"sid": result.session_id},
        ).first()
        assert session_row is not None
        assert session_row.status == "completed"
        assert session_row.jobs_new == 1


class TestSaveCleanedJobsBatchIsolation:
    """Regression coverage for a real production incident: a single bad
    row in a batch silently discarded the *entire* batch, including jobs
    that individually succeeded, plus the ops.scraping_sessions bookkeeping
    row itself (confirmed live: an 18-job Remotive run with one
    constraint-violating salary range persisted zero rows anywhere).

    Root cause: `save_cleaned_jobs` ran every job directly on the shared
    session with a plain try/except. Once one job's INSERT hit a CHECK
    constraint, PostgreSQL marked the whole transaction aborted; every
    later statement in that same transaction -- other jobs' inserts, and
    the final `finish_scraping_session` UPDATE -- failed too, and the
    resulting exception propagating out of `get_session()`'s context
    manager rolled back everything, silently.

    `save_cleaned_jobs` was previously untested at both the unit and
    integration level -- this class is new coverage, not a rewrite of an
    existing test.
    """

    def test_one_bad_job_does_not_roll_back_the_rest_of_the_batch(
        self, db_session, make_cleaned_job
    ):
        repo = JobRepository()
        source_id = repo.get_source_id_by_code(db_session, "remoteok")
        session_id = repo.create_scraping_session(db_session, source_id)

        good_job_1 = _remoteok_style_job(make_cleaned_job, source_job_id="991001")
        # salary_min > salary_max deliberately violates
        # ck_job_salaries_range / ck_job_salaries_normalized_range --
        # the exact shape of the real Remotive incident this regresses.
        bad_job = _remoteok_style_job(
            make_cleaned_job,
            source_job_id="991002",
            salary_min=312000,
            salary_max=52000,
        )
        good_job_2 = _remoteok_style_job(make_cleaned_job, source_job_id="991003")

        counts = repo.save_cleaned_jobs(
            session=db_session,
            jobs=[good_job_1, bad_job, good_job_2],
            source_id=source_id,
            session_id=session_id,
        )

        assert counts["inserted"] == 2
        assert counts["failed"] == 1

        # The two good jobs must actually be persisted, not just counted
        # as "inserted" in Python while the real transaction discarded
        # them -- this is precisely what went wrong in production.
        rows = db_session.execute(
            text(
                "SELECT source_job_id FROM core.jobs "
                "WHERE source_job_id IN ('991001', '991002', '991003') "
                "ORDER BY source_job_id"
            )
        ).scalars().all()
        assert rows == ["991001", "991003"]

        # The batch-level bookkeeping (the row this exact incident wiped
        # out entirely) must also survive the one bad job.
        session_row = db_session.execute(
            text(
                "SELECT status, jobs_new, jobs_failed FROM ops.scraping_sessions "
                "WHERE session_id = :sid"
            ),
            {"sid": session_id},
        ).first()
        assert session_row is not None
        # save_cleaned_jobs itself never touches jobs_new/jobs_failed --
        # only finish_scraping_session does, called separately below. The
        # meaningful assertion here is simply that this row still EXISTS
        # and is reachable at all (it's the exact row the real incident
        # wiped out entirely).
        assert session_row.status == "running"

        # Session must still be usable afterward -- the whole point of a
        # savepoint over a bare try/except.
        repo.finish_scraping_session(
            session=db_session,
            session_id=session_id,
            status="partial",
            jobs_found=3,
            jobs_new=counts["inserted"],
            jobs_updated=counts["updated"],
            jobs_failed=counts["failed"],
            pages_scraped=1,
        )
        finished_row = db_session.execute(
            text(
                "SELECT status, jobs_new, jobs_failed, finished_at FROM ops.scraping_sessions "
                "WHERE session_id = :sid"
            ),
            {"sid": session_id},
        ).first()
        assert finished_row is not None
        assert finished_row.status == "partial"
        assert finished_row.jobs_new == 2
        assert finished_row.jobs_failed == 1
        assert finished_row.finished_at is not None
