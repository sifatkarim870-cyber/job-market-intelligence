"""Tests for the union merge in export_corpus_to_hf.

The exporter used to read local Postgres alone, on the documented assumption
that local was a strict superset of Neon. It was not -- CI scrapes into Neon,
which never flows back to the laptop -- and the result was 5,321 rows deleted
from HF while every check still passed. These pin the union behaviour.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load_exporter():
    """Import scripts/export_corpus_to_hf.py by path.

    pytest's pythonpath is the repo root, which does not include scripts/, and
    this module must be imported as-is rather than copied -- it is the thing
    under test.
    """
    path = ROOT / "scripts" / "export_corpus_to_hf.py"
    spec = importlib.util.spec_from_file_location("export_corpus_to_hf", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


exporter = _load_exporter()

from job_market_intel.corpus.shard_export import SHARD_COLUMNS, to_arrow  # noqa: E402

# SHARD_SELECT order: 0 = source_job_id, 1 = source_code, 2 = source_name.
_JOB_ID, _SRC, _NAME = 0, 1, 2


def _row(job_id: str, source: str, name: str = "Board") -> tuple:
    """A minimal SHARD_SELECT-shaped row; only the key columns matter here."""
    row = [None] * len(SHARD_COLUMNS)
    row[_JOB_ID] = job_id
    row[_SRC] = source
    row[_NAME] = name
    return tuple(row)


class TestMergeSource:
    def test_union_covers_rows_only_one_database_has(self):
        local = [_row("a", "glints"), _row("b", "glints")]
        neon = [_row("b", "glints"), _row("c", "glints")]

        rows, origins = exporter._merge_source(local, neon)

        keys = {(r[_SRC], r[_JOB_ID]) for r in rows}
        assert keys == {("glints", "a"), ("glints", "b"), ("glints", "c")}
        assert len(rows) == 3

    def test_local_wins_a_tie(self):
        """Local is where the derived columns are backfilled, so taking Neon's
        copy for a shared identity would blank them."""
        local = _row("a", "glints", "LOCAL")
        neon = _row("a", "glints", "NEON")

        rows, origins = exporter._merge_source([local], [neon])

        assert len(rows) == 1
        assert rows[0][_NAME] == "LOCAL"
        assert origins == ["local"]

    def test_origins_track_provenance(self):
        local = [_row("a", "glints")]
        neon = [_row("b", "glints"), _row("c", "glints")]

        rows, origins = exporter._merge_source(local, neon)

        by_key = {(r[_SRC], r[_JOB_ID]): o for r, o in zip(rows, origins, strict=True)}
        assert by_key[("glints", "a")] == "local"
        assert by_key[("glints", "b")] == "neon"
        assert by_key[("glints", "c")] == "neon"

    def test_same_job_id_in_different_sources_is_not_a_collision(self):
        """Natural key is the pair, never job_id: each database has its own
        sequence, so 12345 in one is unrelated to 12345 in the other."""
        local = [_row("12345", "glints")]
        neon = [_row("12345", "jobinja")]

        rows, _ = exporter._merge_source(local, neon)

        assert len(rows) == 2

    def test_empty_inputs(self):
        assert exporter._merge_source([], []) == ([], [])
        rows, origins = exporter._merge_source([], [_row("a", "glints")])
        assert len(rows) == 1
        assert origins == ["neon"]

    def test_real_world_split_is_recovered(self):
        """Neither database is a superset: local holds jobvision and greenhouse,
        Neon holds glints. Exporting one alone loses rows."""
        local = [_row(f"jv{i}", "jobvision") for i in range(3)]
        local += [_row(f"gh{i}", "greenhouse") for i in range(2)]
        neon = [_row("jv0", "jobvision")]  # shared, local must win
        neon += [_row(f"gl{i}", "glints") for i in range(4)]

        rows, origins = exporter._merge_source(local, neon)

        # jv0 is shared and counted once; jv1-2 and gh0-1 are local-only;
        # gl0-3 are neon-only. 1 + 2 + 2 + 4 = 9.
        assert len(rows) == 9
        assert origins.count("local") == 5  # jv0 ties go to local
        assert origins.count("neon") == 4


class TestNeonDsnResolution:
    def test_absent_env_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(exporter, "ENV_PATH", tmp_path / "nope.env")
        assert exporter.neon_dsn() is None

    def test_dsn_pointing_at_local_is_rejected(self, tmp_path, monkeypatch):
        """The same URL as local is a misconfiguration, not a second database."""
        env = tmp_path / ".env"
        env.write_text(f"DATABASE_URL={exporter.LOCAL_DSN}\n", encoding="utf-8")
        monkeypatch.setattr(exporter, "ENV_PATH", env)
        assert exporter.neon_dsn() is None

    def test_plain_postgresql_scheme_is_upgraded(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text(
            "DATABASE_URL=postgresql://user:pw@db.example.com/neondb\n", encoding="utf-8"
        )
        monkeypatch.setattr(exporter, "ENV_PATH", env)
        dsn = exporter.neon_dsn()
        assert dsn == "postgresql+psycopg://user:pw@db.example.com/neondb"

    def test_quotes_are_stripped(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text('DATABASE_URL="postgres://u:p@db.example.com/x"\n', encoding="utf-8")
        monkeypatch.setattr(exporter, "ENV_PATH", env)
        assert exporter.neon_dsn() == "postgresql+psycopg://u:p@db.example.com/x"

    def test_non_postgres_url_is_ignored(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("DATABASE_URL=sqlite:///local.db\n", encoding="utf-8")
        monkeypatch.setattr(exporter, "ENV_PATH", env)
        assert exporter.neon_dsn() is None


class TestToArrowOrigins:
    def _row(self) -> tuple:
        return tuple([None] * len(SHARD_COLUMNS))

    def test_single_origin_still_supported(self):
        table = to_arrow([self._row()], "local")
        assert table.column("origin").to_pylist() == ["local"]

    def test_per_row_origins(self):
        table = to_arrow([self._row(), self._row()], ["local", "neon"])
        assert table.column("origin").to_pylist() == ["local", "neon"]

    def test_mismatched_origin_count_is_rejected(self):
        with pytest.raises(ValueError):
            to_arrow([self._row(), self._row()], ["local"])

    def test_all_null_column_is_typed_string(self):
        """An all-NULL column must not infer Arrow's "null" type, which later
        breaks a cast when shards are unioned."""
        table = to_arrow([self._row()], "neon")
        first = table.column(table.column_names[0])
        assert str(first.type) in ("string", "null")
