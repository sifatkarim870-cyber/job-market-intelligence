"""tests/unit/corpus/test_snapshot_merge_key.py

``export_corpus_to_hf.py`` used to dedupe the local/Neon union on
``(source_code, source_job_id)``, leaving ``posting_date`` out of the key. That
is not the schema's natural key -- ``uq_jobs_source_natural_key`` is
``(source_id, source_job_id, posting_date)`` -- and the mismatch silently
deleted 38 real rows from Hugging Face on 2026-10-11.

A source that re-lists a posting on a later date stores it as a NEW row with a
different ``posting_date``, which is exactly why the constraint includes that
column. Those rows carry their own ``core.job_descriptions`` entries, since
``pk_jobs`` is ``(job_id, posting_date)`` and ``job_descriptions`` is
``PRIMARY KEY (job_id)``.

The count guard in the exporter did catch the resulting shortfall, but reported
it as "38 rows behind the database" with no explanation -- which reads as
harmless database growth rather than data loss. These tests pin the key so the
row loss cannot come back quietly.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "export_corpus_to_hf.py"


def _module():
    spec = importlib.util.spec_from_file_location("export_corpus_to_hf", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _module()


def _row(source_code: str, source_job_id: str, posting_date) -> tuple:
    """A row shaped like SHARD_SELECT output, with only the key columns set."""
    from job_market_intel.corpus.shard_export import SHARD_COLUMNS

    values = [None] * len(SHARD_COLUMNS)
    values[SHARD_COLUMNS.index("source_code")] = source_code
    values[SHARD_COLUMNS.index("source_job_id")] = source_job_id
    values[SHARD_COLUMNS.index("posting_date")] = posting_date
    return tuple(values)


def test_relisting_on_a_later_date_is_not_collapsed(mod):
    """The same posting_id on two dates is two rows, not one.

    This is the exact shape that lost 38 rows: jobvision 1451366 stored as
    posting_date 2026-10-05 and again as 2026-10-11.
    """
    early = _row("jobvision", "1451366", dt.date(2026, 10, 5))
    late = _row("jobvision", "1451366", dt.date(2026, 10, 11))

    rows, origins = mod._merge_source([early, late], [])

    assert len(rows) == 2, "a re-listing on a different posting_date must survive"
    assert origins == ["local", "local"]


def test_identical_key_is_still_deduped(mod):
    """The key must still collapse a genuine duplicate within one database."""
    a = _row("jobvision", "1451366", dt.date(2026, 10, 5))
    b = _row("jobvision", "1451366", dt.date(2026, 10, 5))

    rows, _ = mod._merge_source([a, b], [])

    assert len(rows) == 1


def test_local_wins_a_tie_across_databases(mod):
    """A key present in both databases keeps local's row.

    Local is where requirements/responsibilities/skills were backfilled; taking
    Neon's copy would blank them for every shared row.
    """
    local = _row("reed", "R-1", dt.date(2026, 10, 5))
    neon = _row("reed", "R-1", dt.date(2026, 10, 5))
    from job_market_intel.corpus.shard_export import SHARD_COLUMNS

    local = list(local)
    local[SHARD_COLUMNS.index("requirements")] = "backfilled"
    neon = list(neon)
    neon[SHARD_COLUMNS.index("requirements")] = None

    rows, origins = mod._merge_source([tuple(local)], [tuple(neon)])

    assert len(rows) == 1
    assert origins == ["local"]
    assert rows[0][SHARD_COLUMNS.index("requirements")] == "backfilled"


def test_date_key_normalises_driver_types(mod):
    """date and its string form must produce the same dict key.

    The databases return datetime.date, but the value can arrive as a string
    depending on the driver. Mixing the two in one dict key would defeat the
    dedupe entirely -- the original bug, wearing a different hat.
    """
    as_date = mod._date_key(dt.date(2026, 10, 5))
    as_str = mod._date_key("2026-10-05")
    assert as_date == as_str == "2026-10-05"
    assert mod._date_key(None) is None


def test_merge_key_matches_the_database_constraint(mod):
    """The merge key must be the three columns the unique index actually covers."""
    from job_market_intel.corpus.shard_export import SHARD_COLUMNS

    assert mod._JOB_KEY == (1, 0)
    assert SHARD_COLUMNS[mod._JOB_KEY[0]] == "source_code"
    assert SHARD_COLUMNS[mod._JOB_KEY[1]] == "source_job_id"
    assert SHARD_COLUMNS[mod._DATE_KEY] == "posting_date"
