"""tests/unit/corpus/test_shard_export.py

The shard export is the one piece of this project where a silent mismatch would
be invisible: a column list that disagrees with the SELECT writes a Parquet file
whose values are shifted one column left, and nothing errors -- the file is still
valid Parquet, just wrong. So the agreement is asserted directly.

Also covers the two Arrow behaviours the exporter depends on, both of which bit
during the first real export:
  * an all-NULL column must become a typed (string) column, not Arrow's "null"
    type, or a later ``::VARCHAR`` cast on the union of shards fails;
  * a row of the wrong width must raise rather than be padded.
"""

from __future__ import annotations

import pyarrow as pa
import pytest

from job_market_intel.corpus.shard_export import (
    SHARD_COLUMNS,
    SHARD_SELECT,
    CorpusSettings,
    to_arrow,
)


def _select_aliases() -> list[str]:
    """Top-level SELECT aliases, in order, from the shard query."""
    head = SHARD_SELECT.split("FROM core.jobs", 1)[0]
    # Drop `--` line comments first: the CASE expression above carries an
    # explanatory comment, and a naive comma split would read the comment text
    # as if it were columns.
    lines = [ln.split("--", 1)[0] for ln in head.splitlines()]
    head = "\n".join(lines)
    aliases: list[str] = []
    depth = 0
    current = ""
    for ch in head:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            aliases.append(current)
            current = ""
        else:
            current += ch
    aliases.append(current)
    cleaned = []
    for part in aliases:
        text = part.strip()
        if not text or text.upper() == "SELECT":
            continue
        alias = text.split(" AS ")[-1].strip().lower()
        cleaned.append(alias.split(".")[-1])   # drop the s./d./j. qualifier
    return cleaned


def test_shard_columns_match_the_select() -> None:
    assert _select_aliases() == [c.lower() for c in SHARD_COLUMNS]


def _row(**overrides: object) -> tuple:
    row = [None] * len(SHARD_COLUMNS)
    row[SHARD_COLUMNS.index("source_job_id")] = "12345"
    row[SHARD_COLUMNS.index("source_code")] = "glints"
    row[SHARD_COLUMNS.index("posting_date")] = "2026-10-01"
    for key, value in overrides.items():
        row[SHARD_COLUMNS.index(key)] = value
    return tuple(row)


def test_to_arrow_shapes_a_row_and_stamps_origin() -> None:
    table = to_arrow([_row(title_original="Backend Engineer")], origin="neon")
    assert table.num_rows == 1
    assert table.column_names == [*SHARD_COLUMNS, "origin"]
    assert table.column("origin")[0].as_py() == "neon"
    assert table.column("title_original")[0].as_py() == "Backend Engineer"


def test_to_arrow_types_an_all_null_column_as_string() -> None:
    # country_code is NULL for every row of some sources; Arrow would infer the
    # unusable "null" type and a later cast on the shard union would fail.
    table = to_arrow([_row(), _row()], origin="local")
    assert table.column("country_code").type == pa.string()
    assert table.column("country_code").null_count == 2


def test_to_arrow_rejects_a_row_of_the_wrong_width() -> None:
    with pytest.raises(ValueError, match="expected"):
        to_arrow([("only-one-column",)], origin="neon")  # type: ignore[arg-type]


def test_settings_default_repo_and_prefix() -> None:
    settings = CorpusSettings()
    assert settings.hf_repo.startswith("Shifat2110724169/")
    assert settings.model_config["env_prefix"] == "CORPUS_"
    assert settings.max_rows_per_shard >= 100