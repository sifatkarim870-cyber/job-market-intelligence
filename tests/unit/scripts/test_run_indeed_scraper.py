"""Unit tests for scripts/run_indeed_scraper.py's run-outcome reporting.

Why this exists: the scraper exits 0 for a block, an empty queue and a real
scrape alike, so the summary JSON it optionally writes is the only thing
distinguishing them. That makes the classification itself worth pinning down --
in particular the split between "blocked" and "partial", which exists because a
run that collects jobs and is *then* challenged has done its job and must not be
escalated as the silent zero-job failure CI alerts on.

These import from the script by path rather than as a module: it lives in
scripts/, not in the installed package, and it is not importable as
`run_indeed_scraper` without putting scripts/ on sys.path.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "run_indeed_scraper.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("_run_indeed_scraper", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the module imports job_market_intel, which needs to
    # be importable, and dataclasses-style introspection can trip over a module
    # that is absent from sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_scrape = _load_script()


class TestClassifyOutcome:
    def test_no_block_is_ok_regardless_of_count(self) -> None:
        assert _scrape._classify_outcome(any_blocked=False, jobs_inserted=0) == _scrape.OUTCOME_OK
        assert _scrape._classify_outcome(any_blocked=False, jobs_inserted=16) == _scrape.OUTCOME_OK

    def test_block_with_nothing_collected_is_the_silent_failure(self) -> None:
        """The case CI escalates: challenged, and zero jobs to show for it."""
        assert _scrape._classify_outcome(any_blocked=True, jobs_inserted=0) == (
            _scrape.OUTCOME_BLOCKED
        )

    def test_block_after_real_work_is_partial_not_blocked(self) -> None:
        """Measured locally: 16 jobs over 2 pages, then a challenge on page 2.

        Calling that "blocked" would fail scheduled builds that did their job,
        and could never let a working-but-frequently-challenged scraper reach
        the alerting threshold at all.
        """
        assert _scrape._classify_outcome(any_blocked=True, jobs_inserted=16) == (
            _scrape.OUTCOME_PARTIAL
        )

    def test_partial_and_blocked_are_distinct_outcomes(self) -> None:
        """Guard against the two collapsing back together."""
        assert _scrape.OUTCOME_PARTIAL != _scrape.OUTCOME_BLOCKED


class TestWriteSummary:
    def test_writes_json_to_the_requested_path(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "summary.json"
        _scrape._write_summary(target, {"outcome": "ok", "jobs_inserted": 3})

        assert json.loads(target.read_text(encoding="utf-8")) == {
            "outcome": "ok",
            "jobs_inserted": 3,
        }

    def test_no_path_is_a_no_op(self, tmp_path: Path) -> None:
        # Used by the plain manual invocation, which asks for no summary.
        _scrape._write_summary(None, {"outcome": "ok"})
        assert list(tmp_path.iterdir()) == []

    def test_write_failure_does_not_raise(self, tmp_path: Path) -> None:
        """A missing summary must not turn a completed scrape into a crash.

        CI treats an unreadable summary as "unknown" and declines to count it,
        specifically so that this path failing can't silently disarm alerting --
        but it must not take the run down either.
        """
        # A directory where a file is expected: writing the file raises OSError.
        target = tmp_path / "a_directory"
        target.mkdir()
        _scrape._write_summary(target, {"outcome": "ok"})

    @pytest.mark.parametrize("value", [{"outcome": "blocked"}, {"outcome": "partial"}])
    def test_payload_survives_a_round_trip(self, tmp_path: Path, value: dict) -> None:
        target = tmp_path / "s.json"
        _scrape._write_summary(target, value)
        assert json.loads(target.read_text(encoding="utf-8")) == value
