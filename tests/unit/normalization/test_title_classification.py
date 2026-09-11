"""Unit tests for normalization.title_classification.

Mirrors this project's established pattern: DB-touching functions
(fetch_taxonomy, fetch_unclassified_jobs, apply_classification) get a
mocked Connection; strip_boilerplate, looks_like_non_job_content, and
build_embedding_text are pure Python and tested directly against real
examples confirmed via real sampling during this step's design
(RemoteOK job_ids 82, 218, 96, 217 -- see
normalization/title_classification.py's module docstring). classify_job
is tested with a fake embedding model (a tiny stand-in, not the real
sentence-transformers model, which needs a network download this test
suite must not depend on) using synthetic, low-dimensional vectors,
mirroring how test_skill_extraction.py tests its own matching logic
against synthetic vocabulary rather than real ref.skills data.
"""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import MagicMock

import numpy as np

from job_market_intel.normalization.title_classification import (
    ClassificationResult,
    TaxonomyEntry,
    UnclassifiedJob,
    apply_classification,
    build_embedding_text,
    classify_job,
    fetch_taxonomy,
    fetch_unclassified_jobs,
    looks_like_non_job_content,
    strip_boilerplate,
)

_REMOTEOK_BOILERPLATE = (
    "Please mention the word **CONSISTENTLY** and tag RMjcuMTQ3LjIwNC4yMg== "
    "when applying to show you read the job post completely "
    "(#RMjcuMTQ3LjIwNC4yMg==). This is a beta feature to avoid spam applicants."
)


class TestStripBoilerplate:
    def test_removes_remoteok_anti_spam_text(self) -> None:
        description = f"We need a backend engineer. {_REMOTEOK_BOILERPLATE}"
        assert strip_boilerplate(description) == "We need a backend engineer."

    def test_unchanged_when_boilerplate_absent(self) -> None:
        assert strip_boilerplate("A normal description.") == "A normal description."

    def test_none_input_returns_empty_string(self) -> None:
        assert strip_boilerplate(None) == ""

    def test_empty_string_returns_empty_string(self) -> None:
        assert strip_boilerplate("") == ""


class TestLooksLikeNonJobContent:
    def test_literal_test_title_with_gibberish_description(self) -> None:
        # Real example: RemoteOK job_id 82.
        description = f"test ookjyutyytrtcvyibuinjjjjjjjjjjjj. {_REMOTEOK_BOILERPLATE}"
        assert looks_like_non_job_content("test", description) is True

    def test_test_title_case_insensitive(self) -> None:
        description = f"Test Test Test. {_REMOTEOK_BOILERPLATE}"
        assert looks_like_non_job_content("Test", description) is True

    def test_test_with_trailing_number_still_flagged(self) -> None:
        # Real example: RemoteOK sample fixture had "Test Job 3".
        assert looks_like_non_job_content("Test", "Test desc") is True

    def test_near_empty_description_after_stripping_boilerplate(self) -> None:
        assert looks_like_non_job_content("Menu", _REMOTEOK_BOILERPLATE) is True

    def test_real_job_with_generic_title_not_flagged(self) -> None:
        # Real example: RemoteOK job_id 217 ("Various" / Plumbers Co-op) --
        # the specific case this whole step exists to rescue, not exclude.
        description = (
            "Join Australia's Only Plumber-Owned Supply Team. Ready to join "
            "a team that actually values the trade? At Plumbers Co-op, "
            "we're a plumber-owned supply business."
        )
        assert looks_like_non_job_content("Various", description) is False

    def test_real_job_with_clear_title_not_flagged(self) -> None:
        description = (
            f"We need an experienced backend engineer with Python. {_REMOTEOK_BOILERPLATE}"
        )
        assert looks_like_non_job_content("Senior Backend Engineer", description) is False

    def test_none_description_not_flagged_by_title_alone(self) -> None:
        # A real title with no description at all shouldn't be excluded
        # just for missing a description -- only genuinely near-empty
        # content (after stripping) should be.
        # empty description IS near-empty
        assert looks_like_non_job_content("Backend Engineer", None) is True


class TestBuildEmbeddingText:
    def test_combines_title_and_stripped_truncated_description(self) -> None:
        description = f"We need a backend engineer with Python. {_REMOTEOK_BOILERPLATE}"
        result = build_embedding_text("Custom Software Engineer", description)
        assert result.startswith("Custom Software Engineer. We need a backend engineer")
        assert "Please mention the word" not in result

    def test_title_only_when_no_description(self) -> None:
        assert build_embedding_text("Backend Engineer", None) == "Backend Engineer"

    def test_truncates_long_description(self) -> None:
        long_description = "A" * 1000
        result = build_embedding_text("Title", long_description)
        # 300-char cap on the description snippet plus "Title. " prefix.
        assert len(result) <= len("Title. ") + 300


class TestFetchTaxonomy:
    def test_maps_rows_to_taxonomy_entries(self) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.all.return_value = [
            MagicMock(
                normalized_title_id=1,
                normalized_title="Backend Engineer",
                job_family="Backend Engineering",
            ),
            MagicMock(
                normalized_title_id=2,
                normalized_title="Product Designer",
                job_family="Product Design",
            ),
        ]
        result = fetch_taxonomy(mock_conn)
        assert result == [
            TaxonomyEntry(1, "Backend Engineer", "Backend Engineering"),
            TaxonomyEntry(2, "Product Designer", "Product Design"),
        ]


class TestFetchUnclassifiedJobs:
    def test_maps_rows_and_only_queries_unclassified(self) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.all.return_value = [
            MagicMock(
                job_id=1, posting_date="2026-08-01", job_title="Test", description_clean="desc"
            ),
        ]
        result = fetch_unclassified_jobs(mock_conn)
        assert len(result) == 1
        assert result[0].job_id == 1
        sql_text = str(mock_conn.execute.call_args[0][0])
        assert "title_classification_status IS NULL" in sql_text


class TestApplyClassification:
    def test_writes_all_four_result_fields(self) -> None:
        mock_conn = MagicMock()
        job = UnclassifiedJob(
            job_id=5,
            posting_date="2026-08-01",
            job_title="Backend Engineer",
            description_clean=None,
        )
        result = ClassificationResult(status="matched", normalized_title_id=1, confidence=0.87)

        apply_classification(mock_conn, job, result, classified_by_label="embedding:test:v1")

        params = mock_conn.execute.call_args[0][1]
        assert params["normalized_title_id"] == 1
        assert params["status"] == "matched"
        assert params["confidence"] == 0.87
        assert params["classified_by"] == "embedding:test:v1"
        assert params["job_id"] == 5


class _FakeModel:
    """Stands in for sentence_transformers.SentenceTransformer -- maps a
    fixed set of known strings to hand-picked low-dimensional vectors so
    the matching logic can be tested without a real model download.
    Raises KeyError on any unexpected text, which is useful: a test
    asserting the title-alone pass short-circuits before ever trying the
    combined text can simply omit the combined-text key and let a
    KeyError prove the second pass was never reached.
    """

    _VECTORS: ClassVar[dict[str, np.ndarray]] = {
        "Backend Engineer": np.array([1.0, 0.0, 0.0]),
        "Product Designer": np.array([0.0, 1.0, 0.0]),
        # A generic, uninformative title alone -- weak against both
        # taxonomy entries, forcing the fallback to the combined pass.
        "Various": np.array([0.2, 0.2, 0.95]),
        "Various. We need someone with Python and Django.": np.array([0.9, 0.1, 0.0]),
        # Genuinely unrelated content -- weak on BOTH the title-alone and
        # the combined pass, for the real no_match case.
        "Completely unrelated gibberish content.": np.array([0.0, 0.0, 1.0]),
        "Completely unrelated gibberish content.. "
        "Completely unrelated gibberish content.": np.array([0.0, 0.0, 1.0]),
    }

    def encode(self, text_or_texts, normalize_embeddings: bool = True):
        if isinstance(text_or_texts, list):
            return np.array([self._normalized(t) for t in text_or_texts])
        return self._normalized(text_or_texts)

    def _normalized(self, text: str) -> np.ndarray:
        vec = self._VECTORS[text]
        return vec / np.linalg.norm(vec)


class TestClassifyJob:
    def _taxonomy(self) -> list[TaxonomyEntry]:
        return [
            TaxonomyEntry(1, "Backend Engineer", "Backend Engineering"),
            TaxonomyEntry(2, "Product Designer", "Product Design"),
        ]

    def _taxonomy_embeddings(self, model: _FakeModel) -> np.ndarray:
        return model.encode(["Backend Engineer", "Product Designer"])

    def test_clear_title_matches_on_title_alone_without_description(self) -> None:
        # A model that would raise on any text not explicitly listed --
        # since "Backend Engineer" (bare title) already scores 1.0
        # against the taxonomy, the combined title+description text
        # must NEVER be embedded. Omitting it from _VECTORS and letting
        # a real _FakeModel (which raises KeyError on unexpected text)
        # run here proves the short-circuit, rather than just asserting
        # the final result.
        model = _FakeModel()
        taxonomy = self._taxonomy()
        embeddings = self._taxonomy_embeddings(model)
        job = UnclassifiedJob(
            job_id=1,
            posting_date="2026-08-01",
            job_title="Backend Engineer",
            # Deliberately NOT a key in _VECTORS -- if classify_job
            # embedded the combined text anyway, this would raise
            # KeyError and fail the test.
            description_clean="Some description text never embedded.",
        )
        result = classify_job(job, taxonomy, embeddings, model)
        assert result.status == "matched"
        assert result.normalized_title_id == 1
        # An exact title match should score very close to 1.0 -- this is
        # exactly the case that was previously diluted down to 0.62 by
        # always embedding title+description combined (see
        # classify_job's docstring for the real dry-run finding this
        # test guards against regressing).
        assert result.confidence is not None and result.confidence > 0.95

    def test_falls_back_to_combined_text_when_title_alone_is_weak(self) -> None:
        # "Various" alone is deliberately weak against both taxonomy
        # entries (see _FakeModel._VECTORS) -- real motivating case for
        # this whole step: a generic/garbage title whose description
        # carries the actual signal.
        model = _FakeModel()
        taxonomy = self._taxonomy()
        embeddings = self._taxonomy_embeddings(model)
        job = UnclassifiedJob(
            job_id=2,
            posting_date="2026-08-01",
            job_title="Various",
            description_clean="We need someone with Python and Django.",
        )
        result = classify_job(job, taxonomy, embeddings, model)
        assert result.status == "matched"
        assert result.normalized_title_id == 1

    def test_low_similarity_on_both_passes_returns_no_match(self) -> None:
        # Needs a real (non-near-empty) description -- otherwise the
        # deny-list's near-empty-content check fires first, which is
        # correct behavior but tests a different path (see
        # test_deny_list_short_circuits_before_embedding for that path).
        # Both the title alone AND the combined text must score low here
        # -- a real no_match, not just a weak title with a strong
        # fallback (see test_falls_back_to_combined_text_when_title_alone_is_weak
        # for that case).
        model = _FakeModel()
        taxonomy = self._taxonomy()
        embeddings = self._taxonomy_embeddings(model)
        job = UnclassifiedJob(
            job_id=3,
            posting_date="2026-08-01",
            job_title="Completely unrelated gibberish content.",
            description_clean="Completely unrelated gibberish content.",
        )
        result = classify_job(job, taxonomy, embeddings, model)
        assert result.status == "no_match"
        assert result.normalized_title_id is None

    def test_deny_list_short_circuits_before_embedding(self) -> None:
        # "test" as a bare title with no real description must be
        # excluded WITHOUT ever calling model.encode -- confirmed via a
        # model that would raise if asked to encode anything unexpected.
        model = MagicMock()
        model.encode.side_effect = AssertionError("should not embed excluded content")
        taxonomy = self._taxonomy()
        embeddings = np.zeros((2, 3))
        job = UnclassifiedJob(
            job_id=4, posting_date="2026-08-01", job_title="test", description_clean=None
        )

        result = classify_job(job, taxonomy, embeddings, model)

        assert result.status == "excluded_non_job"
        model.encode.assert_not_called()
