"""Unit tests for normalization.skill_extraction.

Mirrors the project's established pattern: DB-touching functions
(fetch_skill_vocabulary, fetch_unscanned_jobs, apply_skill_extractions)
get a mocked Session; build_term_index and extract_skill_ids are pure
Python and tested directly against synthetic vocabulary + text,
including the specific false-positive regression cases this module was
designed around (R&D, lowercase "go", trailing punctuation on C++/C#).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from job_market_intel.normalization.skill_extraction import (
    DEFAULT_EXTRACTED_BY,
    SkillVocabularyEntry,
    apply_skill_extractions,
    build_term_index,
    extract_skill_ids,
    fetch_skill_vocabulary,
    fetch_unscanned_jobs,
    normalize_skill_term,
)


def _entry(
    skill_id: int, skill_name: str, aliases: list[str] | None = None
) -> SkillVocabularyEntry:
    return SkillVocabularyEntry(
        skill_id=skill_id,
        skill_name=skill_name,
        normalized_skill_name=normalize_skill_term(skill_name),
        aliases=aliases or [],
    )


class TestNormalizeSkillTerm:
    def test_lowercases_strips_and_collapses_whitespace(self) -> None:
        assert normalize_skill_term("  Node.js  ") == "node.js"

    def test_preserves_punctuation_unlike_dedup_normalize_for_matching(self) -> None:
        # The whole point of NOT reusing dedup.normalize_for_matching:
        # punctuation must survive, since ref.skills.normalized_skill_name
        # was seeded without punctuation stripping.
        assert normalize_skill_term("C++") == "c++"
        assert normalize_skill_term("C#") == "c#"
        assert normalize_skill_term("ASP.NET") == "asp.net"


class TestBuildTermIndex:
    def test_short_terms_keep_original_case(self) -> None:
        vocab = [_entry(1, "R"), _entry(2, "Go", aliases=["golang"])]

        short_terms, long_terms = build_term_index(vocab)

        assert short_terms["R"] == 1
        assert short_terms["Go"] == 2
        assert "golang" in long_terms  # 6 chars, long

    def test_long_terms_lowercased(self) -> None:
        vocab = [_entry(1, "PostgreSQL", aliases=["postgres"])]

        short_terms, long_terms = build_term_index(vocab)

        assert long_terms["postgresql"] == 1
        assert long_terms["postgres"] == 1
        assert short_terms == {}

    def test_threshold_is_exactly_two_characters(self) -> None:
        vocab = [_entry(1, "Go"), _entry(2, "SQL")]  # 2 chars vs 3 chars

        short_terms, long_terms = build_term_index(vocab)

        assert "Go" in short_terms
        assert "sql" in long_terms

    def test_empty_vocabulary_returns_empty_dicts(self) -> None:
        assert build_term_index([]) == ({}, {})

    def test_skill_with_no_aliases_still_indexes_its_own_name(self) -> None:
        vocab = [_entry(1, "Kubernetes")]

        _, long_terms = build_term_index(vocab)

        assert long_terms["kubernetes"] == 1


class TestExtractSkillIds:
    def test_rd_does_not_match_skill_r(self) -> None:
        # THE regression case this module exists for: "R&D" is
        # conventionally capitalized, so even case-sensitive matching
        # for "R" alone wouldn't stop it -- the boundary must also
        # exclude "&" as a valid character next to a short term.
        short_terms = {"R": 1}
        long_terms: dict[str, int] = {}

        matched = extract_skill_ids(
            "Our R&D team is expanding rapidly this year.", short_terms, long_terms
        )

        assert matched == set()

    def test_standalone_capital_r_does_match(self) -> None:
        short_terms = {"R": 1}
        long_terms: dict[str, int] = {}

        matched = extract_skill_ids(
            "The ideal candidate has experience in R for statistics.",
            short_terms,
            long_terms,
        )

        assert matched == {1}

    def test_lowercase_go_in_ordinary_english_does_not_match(self) -> None:
        short_terms = {"Go": 1}
        long_terms: dict[str, int] = {}

        matched = extract_skill_ids(
            "We want someone willing to go the extra mile.", short_terms, long_terms
        )

        assert matched == set()

    def test_capitalized_go_as_language_does_match(self) -> None:
        short_terms = {"Go": 1}
        long_terms: dict[str, int] = {}

        matched = extract_skill_ids(
            "Our backend stack includes Python, PostgreSQL, and Go.",
            short_terms,
            long_terms,
        )

        assert matched == {1}

    def test_trailing_punctuation_after_cplusplus_still_matches(self) -> None:
        # Regression case: standard \b fails here, since \b requires a
        # \w/\W transition and both "+" and "." are non-word characters
        # -- no transition exists between them.
        short_terms: dict[str, int] = {}
        long_terms = {"c++": 1}

        matched = extract_skill_ids("Experience with C++.", short_terms, long_terms)

        assert matched == {1}

    def test_csharp_symbol_matches_with_trailing_comma(self) -> None:
        short_terms = {"C#": 1}
        long_terms: dict[str, int] = {}

        matched = extract_skill_ids("Skilled in C#, Java, and Go.", short_terms, long_terms)

        assert matched == {1}

    def test_long_term_matches_case_insensitively(self) -> None:
        short_terms: dict[str, int] = {}
        long_terms = {"postgresql": 1}

        matched = extract_skill_ids("We use POSTGRESQL in production.", short_terms, long_terms)

        assert matched == {1}

    def test_long_term_does_not_match_as_substring_of_another_word(self) -> None:
        short_terms: dict[str, int] = {}
        long_terms = {"go": 1}  # hypothetical: even a 2-char term reused as "long" for this test

        # "gopher" contains "go" but is not a standalone occurrence.
        matched = extract_skill_ids("We use a gopher-based tool.", short_terms, long_terms)

        assert matched == set()

    def test_multiple_distinct_skills_all_matched(self) -> None:
        short_terms: dict[str, int] = {}
        long_terms = {"python": 1, "postgresql": 2, "kubernetes": 3}

        matched = extract_skill_ids(
            "Looking for Python experience with PostgreSQL and Kubernetes.",
            short_terms,
            long_terms,
        )

        assert matched == {1, 2, 3}

    def test_empty_description_returns_empty_set(self) -> None:
        assert extract_skill_ids("", {"R": 1}, {"python": 2}) == set()

    def test_no_vocabulary_returns_empty_set(self) -> None:
        assert extract_skill_ids("Some text about R and Python.", {}, {}) == set()


def _mock_session_for_fetch_vocab(rows: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.all.return_value = rows
    session.execute.return_value = result
    return session


class TestFetchSkillVocabulary:
    def test_maps_rows_including_none_aliases_to_empty_list(self) -> None:
        row = MagicMock(
            skill_id=1, skill_name="Python", normalized_skill_name="python", aliases=None
        )
        session = _mock_session_for_fetch_vocab([row])

        vocab = fetch_skill_vocabulary(session)

        assert len(vocab) == 1
        assert vocab[0].aliases == []

    def test_preserves_real_aliases_list(self) -> None:
        row = MagicMock(
            skill_id=2,
            skill_name="JavaScript",
            normalized_skill_name="javascript",
            aliases=["js", "ecmascript"],
        )
        session = _mock_session_for_fetch_vocab([row])

        vocab = fetch_skill_vocabulary(session)

        assert vocab[0].aliases == ["js", "ecmascript"]


class TestFetchUnscannedJobs:
    def test_query_excludes_already_scanned_jobs(self) -> None:
        session = _mock_session_for_fetch_vocab([])

        fetch_unscanned_jobs(session, extracted_by_label=DEFAULT_EXTRACTED_BY)

        sql = " ".join(str(session.execute.call_args[0][0]).split())
        assert "NOT EXISTS" in sql
        assert "bridge.job_skills" in sql
        assert "description_clean IS NOT NULL" in sql

        params = session.execute.call_args[0][1]
        assert params["extracted_by"] == DEFAULT_EXTRACTED_BY


def _mock_session_for_apply(rowcount: int = 1) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.rowcount = rowcount
    session.execute.return_value = result
    return session


class TestApplySkillExtractions:
    def test_inserts_one_row_per_skill(self) -> None:
        session = _mock_session_for_apply(rowcount=1)

        inserted = apply_skill_extractions(
            session, job_id=1, posting_date="2026-01-01", skill_ids={10, 20}
        )

        assert inserted == 2
        assert session.execute.call_count == 2

    def test_uses_required_and_confidence_1_always(self) -> None:
        session = _mock_session_for_apply(rowcount=1)

        apply_skill_extractions(session, job_id=1, posting_date="2026-01-01", skill_ids={10})

        sql, params = session.execute.call_args[0]
        assert "'required'" in str(sql)
        assert "1.0" in str(sql)
        assert params["skill_id"] == 10

    def test_conflict_do_nothing_present(self) -> None:
        session = _mock_session_for_apply(rowcount=1)

        apply_skill_extractions(session, job_id=1, posting_date="2026-01-01", skill_ids={10})

        sql = str(session.execute.call_args[0][0])
        assert "ON CONFLICT" in sql
        assert "DO NOTHING" in sql

    def test_conflicting_row_not_counted_as_inserted(self) -> None:
        session = _mock_session_for_apply(rowcount=0)  # simulates a conflict

        inserted = apply_skill_extractions(
            session, job_id=1, posting_date="2026-01-01", skill_ids={10}
        )

        assert inserted == 0

    def test_empty_skill_ids_is_a_noop(self) -> None:
        session = _mock_session_for_apply()

        inserted = apply_skill_extractions(
            session, job_id=1, posting_date="2026-01-01", skill_ids=set()
        )

        assert inserted == 0
        session.execute.assert_not_called()
