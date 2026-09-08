"""Unit tests for normalization.dedup.

Mirrors tests/unit/db/test_job_repository.py's mocked-Session approach for
the DB-touching functions (fetch_dedup_candidates, apply_duplicate_matches)
for the same reason documented there: the SQL here uses Postgres-specific
schema-qualified table names and `now()`, so a mocked Session (branching on
SQL substring, not call order) is used rather than SQLite. find_duplicate_matches
and normalize_for_matching are pure Python logic and are tested directly,
with no session at all.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from job_market_intel.normalization.config import DedupSettings
from job_market_intel.normalization.dedup import (
    DuplicateMatch,
    JobDedupRecord,
    apply_duplicate_matches,
    fetch_dedup_candidates,
    find_duplicate_matches,
    normalize_for_matching,
)


def _record(
    job_id: int,
    source_id: int,
    source_code: str,
    trust_score: float | None,
    posting_date: date,
    job_title: str = "Senior Data Scientist",
    company_name: str = "Acme Corp",
    content_hash: str = "hash-a",
) -> JobDedupRecord:
    return JobDedupRecord(
        job_id=job_id,
        posting_date=posting_date,
        source_id=source_id,
        source_code=source_code,
        trust_score=trust_score,
        job_title=job_title,
        company_name=company_name,
        content_hash=content_hash,
    )


class TestNormalizeForMatching:
    def test_lowercases(self) -> None:
        assert normalize_for_matching("Senior Data Scientist") == "senior data scientist"

    def test_strips_punctuation_noise(self) -> None:
        assert normalize_for_matching("Acme, Inc.") == normalize_for_matching("Acme Inc")

    def test_collapses_whitespace(self) -> None:
        assert normalize_for_matching("Data   Scientist\n") == "data scientist"

    def test_identical_after_normalization(self) -> None:
        a = normalize_for_matching("Sr. Data Scientist")
        b = normalize_for_matching("Sr Data Scientist")
        assert a == b


class TestFindDuplicateMatches:
    def _settings(self, window_days: int = 3) -> DedupSettings:
        return DedupSettings(posting_date_window_days=window_days)

    def test_no_match_when_only_one_source(self) -> None:
        records = [
            _record(
                1,
                source_id=1,
                source_code="remoteok",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
            ),
            _record(
                2,
                source_id=1,
                source_code="remoteok",
                trust_score=0.75,
                posting_date=date(2026, 8, 2),
            ),
        ]
        matches = find_duplicate_matches(records, settings=self._settings())
        assert matches == []

    def test_match_across_two_sources_within_window(self) -> None:
        records = [
            _record(
                1,
                source_id=1,
                source_code="remoteok",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
            ),
            _record(
                2,
                source_id=2,
                source_code="weworkremotely",
                trust_score=0.75,
                posting_date=date(2026, 8, 2),
            ),
        ]
        matches = find_duplicate_matches(records, settings=self._settings(window_days=3))
        assert len(matches) == 1

    def test_no_match_outside_window(self) -> None:
        records = [
            _record(
                1,
                source_id=1,
                source_code="remoteok",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
            ),
            _record(
                2,
                source_id=2,
                source_code="weworkremotely",
                trust_score=0.75,
                posting_date=date(2026, 8, 10),
            ),
        ]
        matches = find_duplicate_matches(records, settings=self._settings(window_days=3))
        assert matches == []

    def test_no_match_when_title_differs(self) -> None:
        records = [
            _record(
                1,
                source_id=1,
                source_code="remoteok",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
                job_title="Data Scientist",
            ),
            _record(
                2,
                source_id=2,
                source_code="weworkremotely",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
                job_title="Data Engineer",
            ),
        ]
        matches = find_duplicate_matches(records, settings=self._settings())
        assert matches == []

    def test_no_match_when_company_differs(self) -> None:
        records = [
            _record(
                1,
                source_id=1,
                source_code="remoteok",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
                company_name="Acme Corp",
            ),
            _record(
                2,
                source_id=2,
                source_code="weworkremotely",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
                company_name="Widgets Inc",
            ),
        ]
        matches = find_duplicate_matches(records, settings=self._settings())
        assert matches == []

    def test_canonical_is_highest_trust_score(self) -> None:
        records = [
            _record(
                1,
                source_id=1,
                source_code="remotive",
                trust_score=0.70,
                posting_date=date(2026, 8, 1),
            ),
            _record(
                2,
                source_id=2,
                source_code="remoteok",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
            ),
        ]
        matches = find_duplicate_matches(records, settings=self._settings())
        assert len(matches) == 1
        assert matches[0].canonical_job_id == 2
        assert matches[0].duplicate_job_id == 1

    def test_tie_break_is_earliest_posting_date(self) -> None:
        records = [
            _record(
                1,
                source_id=1,
                source_code="remoteok",
                trust_score=0.75,
                posting_date=date(2026, 8, 3),
            ),
            _record(
                2,
                source_id=2,
                source_code="weworkremotely",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
            ),
        ]
        matches = find_duplicate_matches(records, settings=self._settings())
        assert len(matches) == 1
        assert matches[0].canonical_job_id == 2  # earlier posting_date
        assert matches[0].duplicate_job_id == 1

    def test_null_trust_score_sorts_lowest(self) -> None:
        records = [
            _record(
                1,
                source_id=1,
                source_code="new_source",
                trust_score=None,
                posting_date=date(2026, 8, 1),
            ),
            _record(
                2,
                source_id=2,
                source_code="remoteok",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
            ),
        ]
        matches = find_duplicate_matches(records, settings=self._settings())
        assert len(matches) == 1
        assert matches[0].canonical_job_id == 2
        assert matches[0].duplicate_job_id == 1

    def test_three_way_match_only_flags_against_single_canonical(self) -> None:
        records = [
            _record(
                1,
                source_id=1,
                source_code="remotive",
                trust_score=0.70,
                posting_date=date(2026, 8, 1),
            ),
            _record(
                2,
                source_id=2,
                source_code="remoteok",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
            ),
            _record(
                3,
                source_id=3,
                source_code="weworkremotely",
                trust_score=0.75,
                posting_date=date(2026, 8, 2),
            ),
        ]
        matches = find_duplicate_matches(records, settings=self._settings())
        assert len(matches) == 2
        canonical_ids = {m.canonical_job_id for m in matches}
        duplicate_ids = {m.duplicate_job_id for m in matches}
        assert canonical_ids == {2}
        assert duplicate_ids == {1, 3}

    def test_content_hash_matched_flag(self) -> None:
        records = [
            _record(
                1,
                source_id=1,
                source_code="remoteok",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
                content_hash="same",
            ),
            _record(
                2,
                source_id=2,
                source_code="weworkremotely",
                trust_score=0.70,
                posting_date=date(2026, 8, 1),
                content_hash="same",
            ),
        ]
        matches = find_duplicate_matches(records, settings=self._settings())
        assert matches[0].content_hash_matched is True

    def test_content_hash_not_required_for_match(self) -> None:
        records = [
            _record(
                1,
                source_id=1,
                source_code="remoteok",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
                content_hash="hash-a",
            ),
            _record(
                2,
                source_id=2,
                source_code="weworkremotely",
                trust_score=0.70,
                posting_date=date(2026, 8, 1),
                content_hash="hash-b",
            ),
        ]
        matches = find_duplicate_matches(records, settings=self._settings())
        assert len(matches) == 1
        assert matches[0].content_hash_matched is False

    def test_same_source_duplicates_are_not_flagged(self) -> None:
        # Two postings from the SAME source with identical normalized
        # title+company are Step 10's concern (source_job_id natural
        # key), not this module's -- confirm they're skipped even when
        # a third, different-source record is also present in the group.
        records = [
            _record(
                1,
                source_id=1,
                source_code="remoteok",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
            ),
            _record(
                2,
                source_id=1,
                source_code="remoteok",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
            ),
            _record(
                3,
                source_id=2,
                source_code="weworkremotely",
                trust_score=0.75,
                posting_date=date(2026, 8, 1),
            ),
        ]
        matches = find_duplicate_matches(records, settings=self._settings())
        # Canonical is job 1 or 2 (tie -- same trust_score/date, dict/list
        # order decides which sorts first); exactly one match against job 3.
        assert len(matches) == 1
        assert matches[0].duplicate_job_id == 3


def _mock_session_for_fetch(rows: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.all.return_value = rows
    session.execute.return_value = result
    return session


class TestFetchDedupCandidates:
    def test_maps_rows_to_records(self) -> None:
        row = MagicMock(
            job_id=1,
            posting_date=date(2026, 8, 1),
            source_id=1,
            source_code="remoteok",
            trust_score=0.75,
            job_title="Engineer",
            company_name="Acme",
            content_hash="abc",
        )
        session = _mock_session_for_fetch([row])

        records = fetch_dedup_candidates(session)

        assert len(records) == 1
        assert records[0].job_id == 1
        assert records[0].trust_score == 0.75

        sql = " ".join(str(session.execute.call_args[0][0]).split())
        assert "job_status = 'active'" in sql
        assert "is_duplicate_of IS NULL" in sql

    def test_null_trust_score_stays_none(self) -> None:
        row = MagicMock(
            job_id=1,
            posting_date=date(2026, 8, 1),
            source_id=1,
            source_code="new_source",
            trust_score=None,
            job_title="Engineer",
            company_name="Acme",
            content_hash="abc",
        )
        session = _mock_session_for_fetch([row])

        records = fetch_dedup_candidates(session)
        assert records[0].trust_score is None


def _mock_session_for_apply(update_rowcount: int = 1) -> MagicMock:
    session = MagicMock()

    def _execute(stmt, params=None):
        sql = " ".join(str(stmt).split())
        result = MagicMock()
        if sql.startswith("UPDATE core.jobs"):
            result.rowcount = update_rowcount
        return result

    session.execute.side_effect = _execute
    return session


class TestApplyDuplicateMatches:
    def _match(self) -> DuplicateMatch:
        return DuplicateMatch(
            duplicate_job_id=1,
            duplicate_posting_date=date(2026, 8, 1),
            duplicate_source_code="remotive",
            canonical_job_id=2,
            canonical_posting_date=date(2026, 8, 1),
            canonical_source_code="remoteok",
            normalized_title="engineer",
            normalized_company="acme",
            content_hash_matched=False,
        )

    def test_updates_and_logs_when_row_affected(self) -> None:
        session = _mock_session_for_apply(update_rowcount=1)
        updated = apply_duplicate_matches(session, [self._match()])

        assert updated == 1
        executed_sql = [" ".join(str(c.args[0]).split()) for c in session.execute.call_args_list]
        assert any(sql.startswith("UPDATE core.jobs") for sql in executed_sql)
        assert any(sql.startswith("INSERT INTO audit.change_log") for sql in executed_sql)

    def test_skips_audit_log_when_already_flagged(self) -> None:
        # rowcount == 0 simulates a row that was already flagged by a
        # concurrent/prior run since fetch_dedup_candidates ran.
        session = _mock_session_for_apply(update_rowcount=0)
        updated = apply_duplicate_matches(session, [self._match()])

        assert updated == 0
        executed_sql = [" ".join(str(c.args[0]).split()) for c in session.execute.call_args_list]
        assert not any(sql.startswith("INSERT INTO audit.change_log") for sql in executed_sql)

    def test_empty_matches_is_a_noop(self) -> None:
        session = _mock_session_for_apply()
        updated = apply_duplicate_matches(session, [])
        assert updated == 0
        session.execute.assert_not_called()
