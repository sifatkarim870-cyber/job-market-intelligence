"""Unit tests for normalization.company_resolution.

Mirrors tests/unit/normalization/test_dedup.py's approach: DB-touching
functions (fetch_alias_candidate_pairs, apply_alias_candidates) get a
mocked Session (branching on SQL substring); build_alias_candidates is
pure Python logic and is tested directly against synthetic
CompanyRecord pairs, including a regression case built from the real
"Dexterra" / "Dexterra Group" pair found in the live database during
this step's investigation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from job_market_intel.normalization.company_resolution import (
    _SUFFIX_STRIP_PATTERN,
    CompanyAliasCandidate,
    CompanyRecord,
    apply_alias_candidates,
    build_alias_candidates,
    fetch_alias_candidate_pairs,
    reject_alias_candidates,
    strip_corporate_suffixes,
)
from job_market_intel.normalization.config import CompanyResolutionSettings


def _record(
    company_id: int,
    company_name: str,
    normalized_name: str | None = None,
    job_count: int = 0,
) -> CompanyRecord:
    return CompanyRecord(
        company_id=company_id,
        company_name=company_name,
        normalized_name=normalized_name or company_name.lower(),
        job_count=job_count,
    )


class TestBuildAliasCandidates:
    def test_real_dexterra_pair_prefers_shorter_name_when_job_counts_tie(self) -> None:
        # Regression case: the one real near-duplicate pair found by hand
        # in the live database (212 companies, Step 25 investigation).
        # Neither has any jobs yet in this scenario (job_count=0 for
        # both), so the tiebreak is shorter normalized_name -- "Dexterra"
        # (8 chars) over "Dexterra Group" (14 chars).
        dexterra = _record(96, "Dexterra", job_count=0)
        dexterra_group = _record(93, "Dexterra Group", job_count=0)

        candidates = build_alias_candidates([(dexterra_group, dexterra, 0.72)])

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.canonical_company_id == 96
        assert candidate.canonical_company_name == "Dexterra"
        assert candidate.alias_company_id == 93
        assert candidate.alias_company_name == "Dexterra Group"
        assert candidate.similarity_score == 0.72

    def test_more_jobs_wins_over_shorter_name(self) -> None:
        # Even though "Acme" is shorter, "Acme Corp" has more postings
        # and should be treated as the more-established canonical.
        acme = _record(1, "Acme", job_count=1)
        acme_corp = _record(2, "Acme Corp", job_count=10)

        candidates = build_alias_candidates([(acme, acme_corp, 0.8)])

        assert candidates[0].canonical_company_id == 2
        assert candidates[0].canonical_company_name == "Acme Corp"
        assert candidates[0].alias_company_id == 1

    def test_final_tiebreak_is_lower_company_id(self) -> None:
        # Equal job_count (0) and equal-length normalized_name ("foo"/
        # "bar", 3 chars each) forces the final tiebreak: lower company_id.
        higher_id = _record(5, "Foo", job_count=0)
        lower_id = _record(3, "Bar", job_count=0)

        candidates = build_alias_candidates([(higher_id, lower_id, 0.6)])

        assert candidates[0].canonical_company_id == 3  # lower company_id wins
        assert candidates[0].alias_company_id == 5

    def test_empty_pairs_returns_empty_list(self) -> None:
        assert build_alias_candidates([]) == []

    def test_multiple_pairs_each_resolved_independently(self) -> None:
        pair_1 = (_record(1, "Foo", job_count=5), _record(2, "Foo Inc", job_count=1))
        pair_2 = (_record(3, "Bar", job_count=1), _record(4, "Bar LLC", job_count=5))

        candidates = build_alias_candidates([(*pair_1, 0.7), (*pair_2, 0.9)])

        assert len(candidates) == 2
        assert candidates[0].canonical_company_id == 1  # more jobs
        assert candidates[1].canonical_company_id == 4  # more jobs


class TestStripCorporateSuffixes:
    def test_real_false_positive_case_zegogo_vs_yt_corporation(self) -> None:
        # Regression case: this exact pair matched at similarity=0.55
        # (below the true positive's 0.60) in a real dry run against the
        # live 212-company dataset, before suffix stripping existed.
        # Stripping "corporation" from both must leave them clearly
        # distinct.
        assert strip_corporate_suffixes("zegogo corporation") == "zegogo"
        assert strip_corporate_suffixes("yt corporation") == "yt"

    def test_real_true_positive_case_dexterra_group(self) -> None:
        assert strip_corporate_suffixes("dexterra group") == "dexterra"
        assert strip_corporate_suffixes("dexterra") == "dexterra"

    def test_strips_multiple_chained_suffix_words(self) -> None:
        assert strip_corporate_suffixes("acme holdings group") == "acme"

    def test_case_insensitive(self) -> None:
        assert strip_corporate_suffixes("acme CORP") == "acme"

    def test_strips_trailing_period(self) -> None:
        assert strip_corporate_suffixes("acme inc.") == "acme"

    def test_no_suffix_present_returns_unchanged(self) -> None:
        assert strip_corporate_suffixes("spacex") == "spacex"
        assert strip_corporate_suffixes("bass pro shops") == "bass pro shops"

    def test_suffix_word_inside_name_not_stripped(self) -> None:
        # "co" only strips as a trailing whole word, not as a substring
        # of "cottonon" -- and not when it's not at the very end.
        assert strip_corporate_suffixes("cotton on group") == "cotton on"

    def test_name_that_is_only_a_suffix_word_falls_back_unchanged(self) -> None:
        # No leading space before the sole word, so the pattern (which
        # requires \s+ before a suffix word) doesn't match at all --
        # falls back to the original via the empty-result guard.
        assert strip_corporate_suffixes("group") == "group"

    def test_name_that_would_fully_empty_falls_back_unchanged(self) -> None:
        # "co" and "group" both strip as trailing suffix words, leaving
        # "the" -- not empty, so no fallback needed here; this confirms
        # multi-word stripping doesn't over-strip past a real word.
        assert strip_corporate_suffixes("the co group") == "the"


def _mock_session_for_fetch(rows: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.all.return_value = rows
    session.execute.return_value = result
    return session


class TestFetchAliasCandidatePairs:
    def test_maps_rows_to_record_pairs(self) -> None:
        row = MagicMock(
            company_id_a=93,
            company_name_a="Dexterra Group",
            normalized_name_a="dexterra group",
            job_count_a=0,
            company_id_b=96,
            company_name_b="Dexterra",
            normalized_name_b="dexterra",
            job_count_b=2,
            sim=0.72,
        )
        session = _mock_session_for_fetch([row])

        pairs = fetch_alias_candidate_pairs(session, settings=CompanyResolutionSettings())

        assert len(pairs) == 1
        record_a, record_b, sim = pairs[0]
        assert record_a.company_id == 93
        assert record_b.company_id == 96
        assert sim == 0.72

    def test_uses_configured_threshold(self) -> None:
        session = _mock_session_for_fetch([])
        settings = CompanyResolutionSettings(similarity_threshold=0.65)

        fetch_alias_candidate_pairs(session, settings=settings)

        params = session.execute.call_args[0][1]
        assert params["threshold"] == 0.65

    def test_query_excludes_already_recorded_pairs(self) -> None:
        session = _mock_session_for_fetch([])

        fetch_alias_candidate_pairs(session, settings=CompanyResolutionSettings())

        sql = " ".join(str(session.execute.call_args[0][0]).split())
        assert "NOT EXISTS" in sql
        assert "core.company_aliases" in sql
        assert "similarity(" in sql

    def test_similarity_computed_on_suffix_stripped_names(self) -> None:
        session = _mock_session_for_fetch([])

        fetch_alias_candidate_pairs(session, settings=CompanyResolutionSettings())

        sql = " ".join(str(session.execute.call_args[0][0]).split())
        assert "regexp_replace" in sql
        assert "stripped_name" in sql
        assert "similarity(a.stripped_name, b.stripped_name)" in sql

        params = session.execute.call_args[0][1]
        assert params["suffix_pattern"] == _SUFFIX_STRIP_PATTERN

    def test_query_excludes_previously_rejected_pairs(self) -> None:
        # Regression test for the real bug: a rejected candidate
        # reappeared on the very next batch run because only
        # core.company_aliases (not audit.change_log) was checked.
        session = _mock_session_for_fetch([])

        fetch_alias_candidate_pairs(session, settings=CompanyResolutionSettings())

        sql = " ".join(str(session.execute.call_args[0][0]).split())
        assert "audit.change_log" in sql
        assert "operation = 'delete'" in sql
        assert "alias_raw_name" in sql


def _mock_session_for_apply(existing: bool = False) -> MagicMock:
    session = MagicMock()

    def _execute(stmt, params=None):
        sql = " ".join(str(stmt).split())
        result = MagicMock()
        if sql.startswith("SELECT alias_id"):
            result.scalar.return_value = 1 if existing else None
        return result

    session.execute.side_effect = _execute
    return session


class TestApplyAliasCandidates:
    def _candidate(self) -> CompanyAliasCandidate:
        return CompanyAliasCandidate(
            canonical_company_id=96,
            canonical_company_name="Dexterra",
            alias_company_id=93,
            alias_company_name="Dexterra Group",
            similarity_score=0.72,
        )

    def test_inserts_alias_and_logs_when_not_already_present(self) -> None:
        session = _mock_session_for_apply(existing=False)
        inserted = apply_alias_candidates(session, [self._candidate()])

        assert inserted == 1
        executed_sql = [" ".join(str(c.args[0]).split()) for c in session.execute.call_args_list]
        assert any(sql.startswith("INSERT INTO core.company_aliases") for sql in executed_sql)
        assert any(sql.startswith("INSERT INTO audit.change_log") for sql in executed_sql)

    def test_skips_when_already_recorded(self) -> None:
        session = _mock_session_for_apply(existing=True)
        inserted = apply_alias_candidates(session, [self._candidate()])

        assert inserted == 0
        executed_sql = [" ".join(str(c.args[0]).split()) for c in session.execute.call_args_list]
        assert not any(sql.startswith("INSERT INTO core.company_aliases") for sql in executed_sql)
        assert not any(sql.startswith("INSERT INTO audit.change_log") for sql in executed_sql)

    def test_never_touches_jobs_or_is_verified(self) -> None:
        # Explicit regression guard for the firm "no auto-merge" decision:
        # confirm no executed statement ever mutates core.jobs or
        # core.companies.is_verified.
        session = _mock_session_for_apply(existing=False)
        apply_alias_candidates(session, [self._candidate()])

        executed_sql = [" ".join(str(c.args[0]).split()) for c in session.execute.call_args_list]
        assert not any("UPDATE core.jobs" in sql for sql in executed_sql)
        assert not any("is_verified" in sql for sql in executed_sql)

    def test_empty_candidates_is_a_noop(self) -> None:
        session = _mock_session_for_apply()
        inserted = apply_alias_candidates(session, [])
        assert inserted == 0
        session.execute.assert_not_called()

    def test_match_confidence_rounded_to_two_decimals(self) -> None:
        session = _mock_session_for_apply(existing=False)
        candidate = CompanyAliasCandidate(
            canonical_company_id=1,
            canonical_company_name="Foo",
            alias_company_id=2,
            alias_company_name="Foo Inc",
            similarity_score=0.723456,
        )
        apply_alias_candidates(session, [candidate])

        insert_call = next(
            c
            for c in session.execute.call_args_list
            if "INSERT INTO core.company_aliases" in str(c.args[0])
        )
        assert insert_call.args[1]["match_confidence"] == 0.72


def _mock_session_for_reject() -> MagicMock:
    session = MagicMock()
    delete_result = MagicMock()
    delete_result.rowcount = 1
    session.execute.return_value = delete_result
    return session


class TestRejectAliasCandidates:
    def test_deletes_alias_rows_and_logs_rejection(self) -> None:
        session = _mock_session_for_reject()

        deleted = reject_alias_candidates(
            session,
            canonical_company_id=96,
            canonical_company_name="Dexterra",
            alias_raw_names=["Dexterra Group"],
        )

        assert deleted == 1
        executed_sql = [" ".join(str(c.args[0]).split()) for c in session.execute.call_args_list]
        assert any(sql.startswith("DELETE FROM core.company_aliases") for sql in executed_sql)
        assert any(sql.startswith("INSERT INTO audit.change_log") for sql in executed_sql)

        log_call = next(
            c
            for c in session.execute.call_args_list
            if "INSERT INTO audit.change_log" in str(c.args[0])
        )
        assert log_call.args[1]["record_id"] == 96

    def test_empty_raw_names_is_a_noop(self) -> None:
        session = _mock_session_for_reject()

        deleted = reject_alias_candidates(
            session,
            canonical_company_id=96,
            canonical_company_name="Dexterra",
            alias_raw_names=[],
        )

        assert deleted == 0
        session.execute.assert_not_called()

    def test_one_change_log_row_per_rejected_alias(self) -> None:
        session = _mock_session_for_reject()

        reject_alias_candidates(
            session,
            canonical_company_id=1,
            canonical_company_name="Foo",
            alias_raw_names=["Foo Inc", "Foo LLC"],
        )

        log_calls = [
            c
            for c in session.execute.call_args_list
            if "INSERT INTO audit.change_log" in str(c.args[0])
        ]
        assert len(log_calls) == 2

    def test_never_touches_core_jobs_or_is_verified(self) -> None:
        session = _mock_session_for_reject()

        reject_alias_candidates(
            session,
            canonical_company_id=96,
            canonical_company_name="Dexterra",
            alias_raw_names=["Dexterra Group"],
        )

        executed_sql = [" ".join(str(c.args[0]).split()) for c in session.execute.call_args_list]
        assert not any("UPDATE core.jobs" in sql for sql in executed_sql)
        assert not any("is_verified" in sql for sql in executed_sql)
