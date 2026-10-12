"""Prove export_translation_worklist.py selects and shapes rows correctly.

The live corpus has nothing outstanding (every non-English description already
has an English value), so the only way to test the selection query is against
a scratch database built for it -- otherwise the happy path is never
exercised and a broken query would look like a healthy "nothing to translate".
"""

import importlib.util
import pathlib

import duckdb
import pytest

_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[2] / "scripts" / "export_translation_worklist.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("export_translation_worklist", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


w = _load()

# Imported after _load() because that call execs the script under test, and
# ruff wants imports at the top (E402). F811 is a false positive here: a pytest
# fixture is imported once and then referenced as a test parameter, which is
# exactly the pattern being flagged.
from tests.unit.fixtures.worklist_db import (  # noqa: E402, F401, F811
    fixture_engine,
)

LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"


class TestSelectionAgainstKnownRows:
    """Exercised against a scratch database with known select/skip cases.

    The live corpus has nothing outstanding, so against it every assertion
    below would pass vacuously and a broken query would look like a healthy
    "nothing to translate".
    """

    def test_selects_only_the_row_that_needs_translation(self, fixture_engine):
        rows = w.fetch_worklist(fixture_engine, min_length=10, limit=None)
        assert [(r[0], r[1], r[2]) for r in rows] == [("testsrc", "J-FA-1", "fa")]

    def test_skips_english_source_language(self, fixture_engine):
        ids = {r[1] for r in w.fetch_worklist(fixture_engine, min_length=10)}
        assert "J-EN-1" not in ids

    def test_skips_rows_already_translated(self, fixture_engine):
        ids = {r[1] for r in w.fetch_worklist(fixture_engine, min_length=10)}
        assert "J-DONE" not in ids

    def test_skips_descriptions_below_min_length(self, fixture_engine):
        ids = {r[1] for r in w.fetch_worklist(fixture_engine, min_length=10)}
        assert "J-FA-2" not in ids

    def test_skips_rows_with_no_language_code(self, fixture_engine):
        """Undetectable language is not translated blindly."""
        ids = {r[1] for r in w.fetch_worklist(fixture_engine, min_length=10)}
        assert "J-NULL" not in ids

    def test_selected_row_carries_the_full_description(self, fixture_engine):
        rows = w.fetch_worklist(fixture_engine, min_length=10)
        assert rows[0][3].strip() != ""

    def test_empty_result_is_handled_without_error(self, fixture_engine):
        """The corpus being fully translated is the normal case, not an error."""
        rows = w.fetch_worklist(fixture_engine, min_length=100_000)
        assert rows == []


class TestTableShape:
    def test_columns_match_the_overlay_contract(self):
        table = w.build_table([("hrge", "1", "fa", "desc")])
        assert tuple(table.column_names) == w.WORKLIST_COLUMNS

    def test_columns_match_the_live_overlay_file(self):
        """The kernel must not need a schema change, so the columns are
        asserted against the real translations.parquet rather than a copy."""
        import os

        from huggingface_hub import hf_hub_download

        tokfile = pathlib.Path(
            r"D:\Research_Project\JobMarketAnalysisPlatform\DataBase\Hugging_Face_token.txt"
        )
        if not tokfile.exists():
            pytest.skip("no HF token available")
        os.environ.setdefault("HF_TOKEN", tokfile.read_text(encoding="utf-8").strip())
        path = hf_hub_download(
            repo_id="Shifat2110724169/job-market-intel-translations",
            filename="translations.parquet",
            repo_type="dataset",
        )
        live = duckdb.connect().execute(f"DESCRIBE SELECT * FROM '{path}'").fetchall()
        assert [r[0] for r in live] == list(w.WORKLIST_COLUMNS)

    def test_lang_is_the_target_not_the_detected_source(self):
        """Every row in the live overlay has lang='en', including Persian ones."""
        table = w.build_table([("hrge", "1", "fa", "desc")])
        assert table.column("lang").to_pylist() == ["en"]
        assert table.column("language_code").to_pylist() == ["fa"]

    def test_kernel_output_fields_are_null(self):
        table = w.build_table([("hrge", "1", "fa", "desc")])
        for col in ("key", "title_en", "description_en", "method"):
            assert table.column(col).to_pylist() == [None], f"{col} must be left for the kernel"

    def test_identity_is_the_natural_key(self):
        """Never job_id -- each database has its own sequence."""
        table = w.build_table([("jobvision", "1451366", "fa", "d")])
        assert table.column("source_code").to_pylist() == ["jobvision"]
        assert table.column("source_job_id").to_pylist() == ["1451366"]
        assert "job_id" not in table.column_names

    def test_empty_table_still_has_the_right_schema(self):
        table = w.build_table([])
        assert tuple(table.column_names) == w.WORKLIST_COLUMNS
        assert table.num_rows == 0


class TestSummary:
    def test_summary_counts_by_source_and_language(self):
        rows = [
            ("jobvision", "1", "fa", "d"),
            ("jobvision", "2", "fa", "d"),
            ("glints", "3", "id", "d"),
        ]
        out = w.summarise(rows, total_chars=12)
        assert "jobvision=2" in out
        assert "glints=1" in out
        assert "fa=2" in out
