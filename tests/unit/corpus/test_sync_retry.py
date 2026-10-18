"""Test the retry in sync_corpus_from_hf.count_remote_rows."""

from __future__ import annotations

import importlib.util
import pathlib
import time

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "sync_corpus_from_hf.py"


def _module():
    spec = importlib.util.spec_from_file_location("sync_corpus_from_hf", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _module()


FILES = [{"path": "shards/source=x/dt=2026-10-18/part-0.parquet", "bytes": 100}]


class _FakeCursor:
    def __init__(self, script):
        self._script = script

    def fetchone(self):
        return (self._script.pop(0),)

    def __getattr__(self, name):
        def _call(*_args, **_kwargs):
            if self._script and name == "execute":
                return None

        return _call


class _FakeCon:
    """Raises `UnicodeDecodeError` for the first `fail_times` execute(count) calls."""

    def __init__(self, script, fail_times):
        self._script = script
        self._fail = fail_times
        self.executed = 0
        self.closed = False

    def execute(self, sql):
        if "count(*)" in sql:
            self.executed += 1
            if self._fail > 0:
                self._fail -= 1
                raise UnicodeDecodeError("utf-8", b"\xcb", 0, 1, "invalid continuation byte")
            return _FakeCursor(self._script)
        return _FakeCursor([])

    def close(self):
        self.closed = True


def _patch(monkeypatch, mod, connections):
    made: list[_FakeCon] = []

    class _DuckDB:
        @staticmethod
        def connect():
            con = connections.pop(0)
            made.append(con)
            return con

    monkeypatch.setitem(__import__("sys").modules, "duckdb", _DuckDB)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    return made


def test_no_shards_short_circuits(mod):
    assert mod.count_remote_rows([], "owner/repo", "2GB") == {
        "shard_files": 0,
        "rows": None,
        "bytes": 0,
    }


def test_shards_local_is_included_not_just_shards(monkeypatch, mod):
    files = [
        {"path": "shards/source=a/dt=2026-10-18/part-0.parquet", "bytes": 10},
        {"path": "shards_local/source=b/dt=2026-10-18/part-0.parquet", "bytes": 20},
        {"path": "state/ref.countries.parquet", "bytes": 99},
        {"path": "dumps/full.dump", "bytes": 99},
    ]
    con = _FakeCon([42], fail_times=0)
    _patch(monkeypatch, mod, [con])
    result = mod.count_remote_rows(files, "owner/repo", "2GB")
    assert result["shard_files"] == 2, "shards_local/ must be counted alongside shards/"
    assert result["rows"] == 42
    assert result["bytes"] == 30


def test_one_transient_decode_error_is_retried(monkeypatch, mod):
    """The observed failure: a valid corpus that raises UnicodeDecodeError once."""
    first = _FakeCon([], fail_times=1)
    second = _FakeCon([131139], fail_times=0)
    _patch(monkeypatch, mod, [first, second])
    result = mod.count_remote_rows(FILES, "owner/repo", "2GB")
    assert result["rows"] == 131139
    assert first.executed == 1 and first.closed
    assert second.executed == 1


def test_two_transient_errors_are_retried(monkeypatch, mod):
    cons = [_FakeCon([], fail_times=1), _FakeCon([], fail_times=1), _FakeCon([7], fail_times=0)]
    _patch(monkeypatch, mod, cons)
    assert mod.count_remote_rows(FILES, "owner/repo", "2GB")["rows"] == 7


def test_persistent_failure_raises_rather_than_reporting_zero(monkeypatch, mod):
    """A count of 0 or None would be silently wrong; it must be loud."""
    cons = [_FakeCon([], fail_times=1) for _ in range(mod._COUNT_ATTEMPTS)]
    _patch(monkeypatch, mod, cons)
    with pytest.raises(RuntimeError, match="could not read remote row count"):
        mod.count_remote_rows(FILES, "owner/repo", "2GB")
    assert all(c.executed == 1 for c in cons)
    assert all(c.closed for c in cons), "a failed connection must still be closed"


def test_attempts_are_bounded(monkeypatch, mod):
    assert mod._COUNT_ATTEMPTS >= 2, (
        "one retry was enough for both observed failures; zero would leave the "
        "sync no more robust than before"
    )
    assert mod._COUNT_ATTEMPTS <= 5, "a long retry ladder delays the real work"
