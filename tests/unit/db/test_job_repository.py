"""Unit tests for JobRepository and content hashing functions.

save_cleaned_job branch coverage (Step 16)
-------------------------------------------
`save_cleaned_job` (~180 lines) was previously only exercised by
`tests/integration/test_remoteok_pipeline.py`, gated on TEST_DATABASE_URL
— in an environment without a live database, it had zero coverage. This
module's `TestSaveCleanedJobBranches` class closes that gap.

Why a mocked Session, not SQLite (verified, not assumed)
------------------------------------------------------------
`save_cleaned_job`'s SQL calls `now()` (Postgres-specific — SQLite has no
such function) and addresses schema-qualified tables (`core.jobs`,
`salary.job_salaries` — SQLite has no schema concept matching Postgres's).
Routing this through SQLite would mean testing rewritten SQL, not the SQL
that actually ships, so instead:

- `JobRepository.get_or_create_company`, `.get_currency_id_by_code`, and
  `.get_employment_type_id_by_code` are monkeypatched to fixed return
  values, since they're already covered indirectly and aren't what's
  under test here.
- `Session.execute` is replaced with a fake whose return value depends on
  which statement it receives (matched by a SQL substring, not call
  order — so these tests don't silently break if save_cleaned_job's
  internal call order shifts without its behavior changing).

What this proves, and what it doesn't: these tests confirm
`save_cleaned_job` picks the correct branch (insert / update / unchanged)
and, for "updated", touches all three related tables together — the
Python-level decision logic. They do NOT prove the SQL is valid against
real PostgreSQL; that's what `test_remoteok_pipeline.py`'s live-DB
integration tests remain responsible for. The two are complementary, not
redundant.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

from job_market_intel.db.job_repository import JobRepository, compute_job_content_hash


class TestJobContentHashing:
    def test_hash_is_deterministic(self) -> None:
        h1 = compute_job_content_hash(
            job_title="Software Engineer",
            company_name="Acme Corp",
            description_clean="Python developer needed",
            location_cleaned="Remote",
            salary_min=100000,
            salary_max=150000,
        )
        h2 = compute_job_content_hash(
            job_title="Software Engineer",
            company_name="Acme Corp",
            description_clean="Python developer needed",
            location_cleaned="Remote",
            salary_min=100000,
            salary_max=150000,
        )
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest length

    def test_hash_case_and_whitespace_insensitivity_for_company(self) -> None:
        h1 = compute_job_content_hash("Engineer", "ACME CORP ", "desc", "remote", 100, 200)
        h2 = compute_job_content_hash("Engineer", "acme corp", "desc", "remote", 100, 200)
        assert h1 == h2

    def test_hash_differs_when_salary_changes(self) -> None:
        h1 = compute_job_content_hash("Engineer", "Acme", "desc", "remote", 100000, 150000)
        h2 = compute_job_content_hash("Engineer", "Acme", "desc", "remote", 120000, 150000)
        assert h1 != h2

    def test_hash_differs_when_title_changes(self) -> None:
        h1 = compute_job_content_hash("Senior Engineer", "Acme", "desc", "remote", 100000, 150000)
        h2 = compute_job_content_hash("Junior Engineer", "Acme", "desc", "remote", 100000, 150000)
        assert h1 != h2


def _mock_session(
    existing_row: tuple | None,
    new_job_id: int = 999,
    existing_salary: tuple | None = None,
) -> MagicMock:
    """A fake Session whose execute() branches on the SQL text of each
    statement it receives, rather than call order (see module docstring
    for why). `existing_row` is what the "look up existing job by
    (source_id, source_job_id)" SELECT should return -- None simulates no
    existing record (the insert path); a (job_id, posting_date,
    content_hash) tuple simulates a re-scrape of a known job.
    `existing_salary` is what the "look up the current salary.job_salaries
    snapshot before overwriting it" SELECT should return (Step 27) --
    only consulted on the update-changed path; a (salary_min, salary_max)
    tuple, or None to simulate no prior salary row (shouldn't normally
    happen for a job that already exists, but tested defensively).
    """
    session = MagicMock()

    def _execute(stmt, params=None):
        sql = " ".join(str(stmt).split())  # normalize whitespace for substring matching
        result = MagicMock()
        if "FROM core.jobs" in sql and "WHERE source_id" in sql:
            result.first.return_value = existing_row
        elif sql.startswith("INSERT INTO core.jobs"):
            result.scalar.return_value = new_job_id
        elif "FROM salary.job_salaries" in sql and "SELECT salary_min" in sql:
            result.first.return_value = existing_salary
        return result

    session.execute.side_effect = _execute
    return session


class TestSaveCleanedJobBranches:
    """Verifies save_cleaned_job picks the correct branch and touches the
    correct set of tables for each — see module docstring for the mocking
    approach and its (deliberate) limits.
    """

    def _repo(self, monkeypatch, company_id: int = 42, currency_id: int = 7) -> JobRepository:
        repo = JobRepository()
        monkeypatch.setattr(repo, "get_or_create_company", lambda *a, **k: company_id)
        monkeypatch.setattr(repo, "get_currency_id_by_code", lambda *a, **k: currency_id)
        # employment_type_id: None by default, matching every live source
        # (RemoteOK/Remotive/WWR) today -- individual tests override this
        # via monkeypatch when they specifically need a non-None value.
        monkeypatch.setattr(repo, "get_employment_type_id_by_code", lambda *a, **k: None)
        return repo

    def test_no_existing_record_inserts(self, monkeypatch, make_cleaned_job) -> None:
        repo = self._repo(monkeypatch)
        session = _mock_session(existing_row=None, new_job_id=999)
        job = make_cleaned_job(source_job_id="1", job_title="Engineer")

        status = repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        assert status == "inserted"
        executed_sql = [" ".join(str(c.args[0]).split()) for c in session.execute.call_args_list]
        assert any(sql.startswith("INSERT INTO core.jobs") for sql in executed_sql)
        assert any(sql.startswith("INSERT INTO core.job_descriptions") for sql in executed_sql)
        assert any(sql.startswith("INSERT INTO salary.job_salaries") for sql in executed_sql)
        # Step 27: every new job gets a Day 1 salary_history row too, not
        # just later changes -- see job_repository.py's insert-path comment.
        assert any(sql.startswith("INSERT INTO salary.salary_history") for sql in executed_sql)

    def test_existing_record_with_matching_hash_is_unchanged(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        repo = self._repo(monkeypatch)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Engineer",
            company_name="Acme",
            description_clean=None,
            location_cleaned=None,
            salary_min=None,
            salary_max=None,
        )
        matching_hash = compute_job_content_hash(
            job_title=job.job_title,
            company_name=job.company_name,
            description_clean=job.description_clean,
            location_cleaned=job.location_cleaned,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
        )
        session = _mock_session(existing_row=(123, date(2026, 1, 1), matching_hash))

        status = repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        assert status == "unchanged"
        executed_sql = [" ".join(str(c.args[0]).split()) for c in session.execute.call_args_list]
        # Only the "still scraped" touch on core.jobs -- descriptions and
        # salary must NOT be touched when nothing actually changed.
        assert any(sql.startswith("UPDATE core.jobs") for sql in executed_sql)
        assert not any(sql.startswith("UPDATE core.job_descriptions") for sql in executed_sql)
        assert not any(sql.startswith("UPDATE salary.job_salaries") for sql in executed_sql)

    def test_existing_record_with_different_hash_is_updated_everywhere(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        repo = self._repo(monkeypatch)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Senior Engineer",
            company_name="Acme",
        )
        stale_hash = "0" * 64  # guaranteed not to match this job's real hash
        session = _mock_session(existing_row=(123, date(2026, 1, 1), stale_hash))

        status = repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        assert status == "updated"
        executed_sql = [" ".join(str(c.args[0]).split()) for c in session.execute.call_args_list]
        # A real content change must update the job, its description, AND
        # its salary row together -- regression guard against a future
        # change accidentally dropping one of the three.
        assert any(sql.startswith("UPDATE core.jobs") for sql in executed_sql)
        assert any(sql.startswith("UPDATE core.job_descriptions") for sql in executed_sql)
        assert any(sql.startswith("UPDATE salary.job_salaries") for sql in executed_sql)


class TestSalaryStandardization:
    """Step 27: normalized_annual_*_usd computation and the conditional
    salary.salary_history append on update. See
    normalization/salary_standardization.py's module docstring and
    job_repository.py's update-path comment for the full rationale.
    """

    def _repo(self, monkeypatch, company_id: int = 42, currency_id: int = 7) -> JobRepository:
        repo = JobRepository()
        monkeypatch.setattr(repo, "get_or_create_company", lambda *a, **k: company_id)
        monkeypatch.setattr(repo, "get_currency_id_by_code", lambda *a, **k: currency_id)
        # employment_type_id: None by default, matching every live source
        # (RemoteOK/Remotive/WWR) today -- individual tests override this
        # via monkeypatch when they specifically need a non-None value.
        monkeypatch.setattr(repo, "get_employment_type_id_by_code", lambda *a, **k: None)
        return repo

    @staticmethod
    def _params_for(session: MagicMock, sql_prefix: str) -> dict:
        for call in session.execute.call_args_list:
            sql = " ".join(str(call.args[0]).split())
            if sql.startswith(sql_prefix):
                return call.args[1]
        raise AssertionError(f"No executed statement started with {sql_prefix!r}")

    @staticmethod
    def _all_sql(session: MagicMock) -> list[str]:
        return [" ".join(str(c.args[0]).split()) for c in session.execute.call_args_list]

    def test_insert_writes_normalized_annual_columns(self, monkeypatch, make_cleaned_job) -> None:
        repo = self._repo(monkeypatch)
        session = _mock_session(existing_row=None, new_job_id=999)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Engineer",
            salary_min=100000,
            salary_max=150000,
            salary_disclosed=True,
        )

        repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        params = self._params_for(session, "INSERT INTO salary.job_salaries")
        # USD/yearly today -> normalization is currently an identity op,
        # but going through the real normalize_annual_salary function
        # (not a hardcoded copy) -- see salary_standardization.py.
        assert params["normalized_annual_min_usd"] == 100000.0
        assert params["normalized_annual_max_usd"] == 150000.0

    def test_insert_with_no_salary_leaves_normalized_columns_none(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        repo = self._repo(monkeypatch)
        session = _mock_session(existing_row=None, new_job_id=999)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Engineer",
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
        )

        repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        params = self._params_for(session, "INSERT INTO salary.job_salaries")
        assert params["normalized_annual_min_usd"] is None
        assert params["normalized_annual_max_usd"] is None

    def test_update_with_substantive_salary_change_appends_history(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        repo = self._repo(monkeypatch)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Senior Engineer",  # differs -> hash changes
            company_name="Acme",
            salary_min=120000,
            salary_max=160000,
            salary_disclosed=True,
        )
        stale_hash = "0" * 64
        session = _mock_session(
            existing_row=(123, date(2026, 1, 1), stale_hash),
            existing_salary=(100000, 150000),
        )

        status = repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        assert status == "updated"
        history_params = self._params_for(session, "INSERT INTO salary.salary_history")
        assert history_params["salary_min"] == 120000
        assert history_params["salary_max"] == 160000
        salary_update_params = self._params_for(session, "UPDATE salary.job_salaries")
        assert salary_update_params["normalized_annual_min_usd"] == 120000.0
        assert salary_update_params["normalized_annual_max_usd"] == 160000.0

    def test_update_with_identical_salary_does_not_append_history(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        repo = self._repo(monkeypatch)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Senior Engineer",  # title change alone triggers the update
            company_name="Acme",
            salary_min=100000,
            salary_max=150000,
            salary_disclosed=True,
        )
        stale_hash = "0" * 64
        session = _mock_session(
            existing_row=(123, date(2026, 1, 1), stale_hash),
            existing_salary=(100000, 150000),  # same figures -> not "changed"
        )

        repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        executed_sql = self._all_sql(session)
        assert not any(sql.startswith("INSERT INTO salary.salary_history") for sql in executed_sql)

    def test_update_where_salary_newly_disclosed_does_not_append_history(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        """A disclosure toggle (previously undisclosed -> now disclosed)
        is deliberately NOT treated as a substantive salary change -- see
        job_repository.py's update-path comment: both old and new values
        must be non-null for an append.
        """
        repo = self._repo(monkeypatch)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Senior Engineer",
            company_name="Acme",
            salary_min=100000,
            salary_max=150000,
            salary_disclosed=True,
        )
        stale_hash = "0" * 64
        session = _mock_session(
            existing_row=(123, date(2026, 1, 1), stale_hash),
            existing_salary=(None, None),  # previously undisclosed
        )

        repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        executed_sql = self._all_sql(session)
        assert not any(sql.startswith("INSERT INTO salary.salary_history") for sql in executed_sql)

    def test_update_where_salary_newly_undisclosed_does_not_append_history(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        """The mirror case: previously disclosed -> now undisclosed."""
        repo = self._repo(monkeypatch)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Senior Engineer",
            company_name="Acme",
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
        )
        stale_hash = "0" * 64
        session = _mock_session(
            existing_row=(123, date(2026, 1, 1), stale_hash),
            existing_salary=(100000, 150000),
        )

        repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        executed_sql = self._all_sql(session)
        assert not any(sql.startswith("INSERT INTO salary.salary_history") for sql in executed_sql)


class TestGeographicResolution:
    """Step 28: core.jobs.location_id is threaded through from
    resolve_and_cache_location on both the insert and content-changed-
    update paths. resolve_and_cache_location itself is monkeypatched here
    (it's unit-tested directly, with its own mocked-session coverage, in
    tests/unit/normalization/test_geographic_resolution.py) -- this class
    only proves save_cleaned_job actually calls it and binds the result,
    not that the resolution logic itself is correct.
    """

    def _repo(
        self,
        monkeypatch,
        company_id: int = 42,
        currency_id: int = 7,
        location_id: int | None = 55,
    ) -> JobRepository:
        repo = JobRepository()
        monkeypatch.setattr(repo, "get_or_create_company", lambda *a, **k: company_id)
        monkeypatch.setattr(repo, "get_currency_id_by_code", lambda *a, **k: currency_id)
        # employment_type_id: None by default, matching every live source
        # (RemoteOK/Remotive/WWR) today -- individual tests override this
        # via monkeypatch when they specifically need a non-None value.
        monkeypatch.setattr(repo, "get_employment_type_id_by_code", lambda *a, **k: None)
        monkeypatch.setattr(
            "job_market_intel.db.job_repository.resolve_and_cache_location",
            lambda *a, **k: location_id,
        )
        return repo

    @staticmethod
    def _params_for(session: MagicMock, sql_prefix: str) -> dict:
        for call in session.execute.call_args_list:
            sql = " ".join(str(call.args[0]).split())
            if sql.startswith(sql_prefix):
                return call.args[1]
        raise AssertionError(f"No executed statement started with {sql_prefix!r}")

    def test_location_id_is_bound_on_insert(self, monkeypatch, make_cleaned_job) -> None:
        repo = self._repo(monkeypatch, location_id=55)
        session = _mock_session(existing_row=None, new_job_id=999)
        job = make_cleaned_job(
            source_job_id="1", job_title="Engineer", location_cleaned="Remote - US"
        )

        repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        params = self._params_for(session, "INSERT INTO core.jobs")
        assert params["location_id"] == 55

    def test_none_location_id_is_bound_as_none_on_insert(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        # resolve_and_cache_location itself returns None for a job with no
        # location text at all (see that function's own tests) -- this
        # confirms save_cleaned_job doesn't choke on or fabricate a value
        # for that case, it just binds None straight through.
        repo = self._repo(monkeypatch, location_id=None)
        session = _mock_session(existing_row=None, new_job_id=999)
        job = make_cleaned_job(source_job_id="1", job_title="Engineer", location_cleaned=None)

        repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        params = self._params_for(session, "INSERT INTO core.jobs")
        assert params["location_id"] is None

    def test_location_id_is_bound_on_content_changed_update(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        repo = self._repo(monkeypatch, location_id=77)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Senior Engineer",
            company_name="Acme",
            location_cleaned="Worldwide",
        )
        stale_hash = "0" * 64
        session = _mock_session(existing_row=(123, date(2026, 1, 1), stale_hash))

        status = repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        assert status == "updated"
        params = self._params_for(session, "UPDATE core.jobs")
        assert params["location_id"] == 77

    def test_unchanged_path_does_not_write_location_id_anywhere(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        # The "still scraped, nothing changed" UPDATE core.jobs statement
        # never touched location_id before Step 28 and must not gain it
        # now -- location_cleaned is part of the content hash, so
        # "unchanged" means it didn't change, and there's nothing to
        # re-bind.
        repo = self._repo(monkeypatch, location_id=55)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Engineer",
            company_name="Acme",
            description_clean=None,
            location_cleaned=None,
            salary_min=None,
            salary_max=None,
        )
        matching_hash = compute_job_content_hash(
            job_title=job.job_title,
            company_name=job.company_name,
            description_clean=job.description_clean,
            location_cleaned=job.location_cleaned,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
        )
        session = _mock_session(existing_row=(123, date(2026, 1, 1), matching_hash))

        status = repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        assert status == "unchanged"
        params = self._params_for(session, "UPDATE core.jobs")
        assert "location_id" not in params


class TestGetExistingSourceJobIds:
    """Direct unit tests for the lookup Reed's pipeline uses to prioritize
    which jobs get a Details call first when a run exceeds its per-run
    cap -- see that method's docstring for the full rationale (every
    processed job still gets a real Details call; this only affects
    which jobs are selected when not everything fits in one run)."""

    def test_empty_candidates_returns_empty_set_without_querying(self) -> None:
        repo = JobRepository()
        session = MagicMock()
        result = repo.get_existing_source_job_ids(session, source_id=1, candidate_source_job_ids=[])
        assert result == set()
        session.execute.assert_not_called()

    def test_returns_only_the_ids_the_database_reports_as_existing(self) -> None:
        repo = JobRepository()
        session = MagicMock()
        session.execute.return_value = [("123",), ("456",)]
        result = repo.get_existing_source_job_ids(
            session, source_id=7, candidate_source_job_ids=["123", "456", "789"]
        )
        assert result == {"123", "456"}
        params = session.execute.call_args.args[1]
        assert params == {"source_id": 7, "candidate_ids": ["123", "456", "789"]}


class TestReferenceLookupHelpers:
    """Direct unit tests for the two lookup helpers that replaced the old
    hardcoded USD/yearly assumption -- see job_repository.py's "Reed
    scraper note" for the full history."""

    def test_get_currency_id_by_code_returns_matching_id(self) -> None:
        repo = JobRepository()
        session = MagicMock()
        session.execute.return_value.scalar.return_value = 7
        result = repo.get_currency_id_by_code(session, "GBP")
        assert result == 7
        params = session.execute.call_args.args[1]
        assert params == {"iso_code": "GBP"}

    def test_get_currency_id_by_code_returns_none_for_unknown_code(self) -> None:
        repo = JobRepository()
        session = MagicMock()
        session.execute.return_value.scalar.return_value = None
        assert repo.get_currency_id_by_code(session, "XXX") is None

    def test_get_employment_type_id_by_code_returns_none_without_querying(self) -> None:
        """code=None is an honest absence (RemoteOK/Remotive/WWR today) --
        must short-circuit, not issue a SELECT with a NULL param."""
        repo = JobRepository()
        session = MagicMock()
        assert repo.get_employment_type_id_by_code(session, None) is None
        session.execute.assert_not_called()

    def test_get_employment_type_id_by_code_returns_matching_id(self) -> None:
        repo = JobRepository()
        session = MagicMock()
        session.execute.return_value.scalar.return_value = 3
        result = repo.get_employment_type_id_by_code(session, "contract")
        assert result == 3
        params = session.execute.call_args.args[1]
        assert params == {"code": "contract"}

    def test_get_employment_type_id_by_code_returns_none_for_unknown_code(self) -> None:
        repo = JobRepository()
        session = MagicMock()
        session.execute.return_value.scalar.return_value = None
        assert repo.get_employment_type_id_by_code(session, "not-a-real-code") is None


class TestEmploymentTypeThreading:
    """Verifies core.jobs.employment_type_id is bound on insert and on a
    content-changed update, mirroring exactly how TestGeographicResolution
    verifies location_id above -- same non-content-hash-derived field,
    same insert/update-only, skip-on-unchanged treatment. This is the
    first source (Reed) to ever populate this column; RemoteOK/Remotive/
    WWR all continue writing NULL via their None employment_type_code.
    """

    def _repo(
        self,
        monkeypatch,
        company_id: int = 42,
        currency_id: int = 7,
        employment_type_id: int | None = 3,
    ) -> JobRepository:
        repo = JobRepository()
        monkeypatch.setattr(repo, "get_or_create_company", lambda *a, **k: company_id)
        monkeypatch.setattr(repo, "get_currency_id_by_code", lambda *a, **k: currency_id)
        monkeypatch.setattr(
            repo, "get_employment_type_id_by_code", lambda *a, **k: employment_type_id
        )
        return repo

    @staticmethod
    def _params_for(session: MagicMock, sql_prefix: str) -> dict:
        for call in session.execute.call_args_list:
            sql = " ".join(str(call.args[0]).split())
            if sql.startswith(sql_prefix):
                return call.args[1]
        raise AssertionError(f"No executed statement started with {sql_prefix!r}")

    def test_employment_type_id_is_bound_on_insert(self, monkeypatch, make_cleaned_job) -> None:
        repo = self._repo(monkeypatch, employment_type_id=3)
        session = _mock_session(existing_row=None, new_job_id=999)
        job = make_cleaned_job(
            source_job_id="1", job_title="Engineer", employment_type_code="contract"
        )

        repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        params = self._params_for(session, "INSERT INTO core.jobs")
        assert params["employment_type_id"] == 3

    def test_none_employment_type_id_is_bound_as_none_on_insert(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        # RemoteOK/Remotive/WWR's actual behavior today: no employment
        # type reported, so employment_type_code=None -> NULL, not a
        # fabricated default.
        repo = self._repo(monkeypatch, employment_type_id=None)
        session = _mock_session(existing_row=None, new_job_id=999)
        job = make_cleaned_job(source_job_id="1", job_title="Engineer")

        repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        params = self._params_for(session, "INSERT INTO core.jobs")
        assert params["employment_type_id"] is None

    def test_employment_type_id_is_bound_on_content_changed_update(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        repo = self._repo(monkeypatch, employment_type_id=5)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Senior Engineer",
            company_name="Acme",
            employment_type_code="full_time",
        )
        stale_hash = "0" * 64
        session = _mock_session(existing_row=(123, date(2026, 1, 1), stale_hash))

        status = repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        assert status == "updated"
        params = self._params_for(session, "UPDATE core.jobs")
        assert params["employment_type_id"] == 5

    def test_unchanged_path_does_not_write_employment_type_id_anywhere(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        repo = self._repo(monkeypatch, employment_type_id=3)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Engineer",
            company_name="Acme",
            description_clean=None,
            location_cleaned=None,
            salary_min=None,
            salary_max=None,
        )
        matching_hash = compute_job_content_hash(
            job_title=job.job_title,
            company_name=job.company_name,
            description_clean=job.description_clean,
            location_cleaned=job.location_cleaned,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
        )
        session = _mock_session(existing_row=(123, date(2026, 1, 1), matching_hash))

        status = repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        assert status == "unchanged"
        params = self._params_for(session, "UPDATE core.jobs")
        assert "employment_type_id" not in params


class TestPerRecordCurrencyAndPayPeriod:
    """Verifies save_cleaned_job reads currency/pay_period off the
    CleanedJob record itself (job.currency_iso_code / job.pay_period),
    not a repository-level constant -- the actual fix for the Step 27 bug
    pattern this whole change exists for. get_currency_id_by_code is
    monkeypatched to assert it's called with the record's own code."""

    def test_currency_code_is_read_from_the_record_not_hardcoded(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        repo = JobRepository()
        monkeypatch.setattr(repo, "get_or_create_company", lambda *a, **k: 42)
        monkeypatch.setattr(repo, "get_employment_type_id_by_code", lambda *a, **k: None)
        seen_codes: list[str] = []

        def _fake_currency_lookup(session, iso_code):
            seen_codes.append(iso_code)
            return 99

        monkeypatch.setattr(repo, "get_currency_id_by_code", _fake_currency_lookup)
        session = _mock_session(existing_row=None, new_job_id=999)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Engineer",
            salary_min=450,
            salary_max=600,
            salary_disclosed=True,
            currency_iso_code="GBP",
            pay_period="daily",
        )

        repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        assert seen_codes == ["GBP"]
        params = session.execute.call_args_list
        salary_insert = next(
            c.args[1]
            for c in params
            if " ".join(str(c.args[0]).split()).startswith("INSERT INTO salary.job_salaries")
        )
        assert salary_insert["currency_id"] == 99
        assert salary_insert["pay_period"] == "daily"

    def test_gbp_daily_salary_normalizes_to_none_with_no_exchange_rate(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        """The concrete case that motivated this whole change: a GBP
        day-rate posting must NOT be silently treated as an annual USD
        figure. With no GBP exchange rate seeded (confirmed real state --
        see normalization/salary_standardization.py), the honest result
        is normalized_annual_*_usd = None, not a wrong number."""
        repo = JobRepository()
        monkeypatch.setattr(repo, "get_or_create_company", lambda *a, **k: 42)
        monkeypatch.setattr(repo, "get_currency_id_by_code", lambda *a, **k: 7)
        monkeypatch.setattr(repo, "get_employment_type_id_by_code", lambda *a, **k: None)
        session = _mock_session(existing_row=None, new_job_id=999)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="AI Engineer",
            salary_min=450,
            salary_max=600,
            salary_disclosed=True,
            currency_iso_code="GBP",
            pay_period="daily",
        )

        repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        params = session.execute.call_args_list
        salary_insert = next(
            c.args[1]
            for c in params
            if " ".join(str(c.args[0]).split()).startswith("INSERT INTO salary.job_salaries")
        )
        assert salary_insert["normalized_annual_min_usd"] is None
        assert salary_insert["normalized_annual_max_usd"] is None
        # And, crucially, the raw native-cadence figures are still stored
        # correctly -- nothing here loses the real £450-600/day data.
        assert salary_insert["salary_min"] == 450
        assert salary_insert["salary_max"] == 600
        assert salary_insert["pay_period"] == "daily"


class TestClosingDateThreading:
    """Verifies CleanedJob.closing_date is correctly bound as a parameter
    in every write path, added alongside We Work Remotely (the first
    source to actually populate this field -- RemoteOK's feed never
    provided one). See job_repository.py's inline comment next to where
    `c_date` is computed for why closing_date is refreshed
    unconditionally in every branch (including "unchanged") rather than
    being folded into the content hash.
    """

    def _repo(self, monkeypatch, company_id: int = 42, currency_id: int = 7) -> JobRepository:
        repo = JobRepository()
        monkeypatch.setattr(repo, "get_or_create_company", lambda *a, **k: company_id)
        monkeypatch.setattr(repo, "get_currency_id_by_code", lambda *a, **k: currency_id)
        # employment_type_id: None by default, matching every live source
        # (RemoteOK/Remotive/WWR) today -- individual tests override this
        # via monkeypatch when they specifically need a non-None value.
        monkeypatch.setattr(repo, "get_employment_type_id_by_code", lambda *a, **k: None)
        return repo

    @staticmethod
    def _params_for(session: MagicMock, sql_prefix: str) -> dict:
        for call in session.execute.call_args_list:
            sql = " ".join(str(call.args[0]).split())
            if sql.startswith(sql_prefix):
                return call.args[1]
        raise AssertionError(f"No executed statement started with {sql_prefix!r}")

    def test_closing_date_is_bound_on_insert(self, monkeypatch, make_cleaned_job) -> None:
        repo = self._repo(monkeypatch)
        session = _mock_session(existing_row=None, new_job_id=999)
        closing_date = datetime(2026, 9, 24, tzinfo=UTC)
        job = make_cleaned_job(source_job_id="1", job_title="Engineer", closing_date=closing_date)

        repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        params = self._params_for(session, "INSERT INTO core.jobs")
        assert params["closing_date"] == closing_date.date()

    def test_none_closing_date_is_bound_as_none_on_insert(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        repo = self._repo(monkeypatch)
        session = _mock_session(existing_row=None, new_job_id=999)
        job = make_cleaned_job(source_job_id="1", job_title="Engineer", closing_date=None)

        repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        params = self._params_for(session, "INSERT INTO core.jobs")
        assert params["closing_date"] is None

    def test_closing_date_is_refreshed_even_when_content_unchanged(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        repo = self._repo(monkeypatch)
        closing_date = datetime(2026, 10, 1, tzinfo=UTC)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Engineer",
            company_name="Acme",
            description_clean=None,
            location_cleaned=None,
            salary_min=None,
            salary_max=None,
            closing_date=closing_date,
        )
        matching_hash = compute_job_content_hash(
            job_title=job.job_title,
            company_name=job.company_name,
            description_clean=job.description_clean,
            location_cleaned=job.location_cleaned,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
        )
        session = _mock_session(existing_row=(123, date(2026, 1, 1), matching_hash))

        status = repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        assert status == "unchanged"
        params = self._params_for(session, "UPDATE core.jobs")
        assert params["closing_date"] == closing_date.date()

    def test_closing_date_is_bound_on_content_changed_update(
        self, monkeypatch, make_cleaned_job
    ) -> None:
        repo = self._repo(monkeypatch)
        closing_date = datetime(2026, 11, 15, tzinfo=UTC)
        job = make_cleaned_job(
            source_job_id="1",
            job_title="Senior Engineer",
            company_name="Acme",
            closing_date=closing_date,
        )
        stale_hash = "0" * 64
        session = _mock_session(existing_row=(123, date(2026, 1, 1), stale_hash))

        status = repo.save_cleaned_job(session, job, source_id=1, session_id=1)

        assert status == "updated"
        params = self._params_for(session, "UPDATE core.jobs")
        assert params["closing_date"] == closing_date.date()

    def test_closing_date_is_not_part_of_content_hash(self) -> None:
        # A closing_date-only change must not, by itself, make the job's
        # content hash differ -- it's operational metadata, not
        # substantive content (see the module-level rationale above).
        h1 = compute_job_content_hash("Engineer", "Acme", "desc", "remote", 100000, 150000)
        h2 = compute_job_content_hash("Engineer", "Acme", "desc", "remote", 100000, 150000)
        assert h1 == h2
        # compute_job_content_hash has no closing_date parameter at all --
        # this is a structural guard, not just a value-equality check.
        import inspect

        assert "closing_date" not in inspect.signature(compute_job_content_hash).parameters


class TestSaveCleanedJobsSavepointWiring:
    """Structural regression guard for the batch-isolation fix: confirms
    `save_cleaned_jobs` routes every job through `db.transaction.transaction`
    (a real SAVEPOINT) rather than calling `save_cleaned_job` directly on
    the shared session. This does NOT prove savepoint rollback semantics
    actually work end-to-end -- that requires real PostgreSQL and is
    covered by
    `tests/integration/test_remoteok_pipeline.py::TestSaveCleanedJobsBatchIsolation`.
    This test exists purely to fail loudly if someone removes the
    `transaction(session)` wrapper in a future refactor, since a plain
    mocked session would otherwise happily "pass" either way and mask the
    regression.
    """

    def test_each_job_is_wrapped_in_its_own_savepoint(self, monkeypatch) -> None:
        from job_market_intel.db import job_repository as job_repository_module

        calls: list[object] = []

        class _FakeTransaction:
            def __init__(self, session: object) -> None:
                calls.append(session)

            def __enter__(self) -> object:
                return self

            def __exit__(self, *exc_info: object) -> bool:
                return False

        monkeypatch.setattr(job_repository_module, "transaction", _FakeTransaction)

        repo = JobRepository()
        fake_session = object()
        monkeypatch.setattr(repo, "save_cleaned_job", lambda **kwargs: "inserted")

        jobs = [MagicMock(source_job_id=f"j{i}") for i in range(3)]
        counts = repo.save_cleaned_jobs(
            session=fake_session, jobs=jobs, source_id=1, session_id=1
        )

        assert counts["inserted"] == 3
        # One savepoint per job, each opened on the shared session -- not
        # one savepoint for the whole batch, and not zero.
        assert calls == [fake_session, fake_session, fake_session]

    def test_one_job_raising_inside_its_savepoint_does_not_abort_the_loop(
        self, monkeypatch
    ) -> None:
        from job_market_intel.db import job_repository as job_repository_module

        class _FakeTransaction:
            def __init__(self, session: object) -> None:
                pass

            def __enter__(self) -> object:
                return self

            def __exit__(self, *exc_info: object) -> bool:
                # A real SAVEPOINT context manager swallows nothing --
                # the exception still propagates to save_cleaned_jobs'
                # own try/except, which is what actually increments
                # counts["failed"]. Returning False here mirrors that.
                return False

        monkeypatch.setattr(job_repository_module, "transaction", _FakeTransaction)

        repo = JobRepository()

        def _fake_save(**kwargs: object) -> str:
            job = kwargs["job"]
            if job.source_job_id == "bad":
                raise ValueError("simulated constraint violation")
            return "inserted"

        monkeypatch.setattr(repo, "save_cleaned_job", _fake_save)

        jobs = [
            MagicMock(source_job_id="good1"),
            MagicMock(source_job_id="bad"),
            MagicMock(source_job_id="good2"),
        ]
        counts = repo.save_cleaned_jobs(session=object(), jobs=jobs, source_id=1, session_id=1)

        assert counts == {"inserted": 2, "updated": 0, "unchanged": 0, "failed": 1}
