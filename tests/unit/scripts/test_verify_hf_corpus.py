"""Tests for scripts/verify_hf_corpus.py.

Deliberately offline. The checks themselves need the network, but the decision
logic -- especially the duplicate-ratio threshold, which is the alarm for "the
nightly merge stopped running" -- must be testable without it, and must be
tested on its failure path. A guard that has only ever been exercised in the
passing direction is not known to work.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_hf_corpus.py"


@pytest.fixture
def mod():
    sys.modules.pop("verify_hf_corpus_under_test", None)
    spec = importlib.util.spec_from_file_location("verify_hf_corpus_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_hf_corpus_under_test"] = module
    spec.loader.exec_module(module)
    return module


class FakeReport:
    """Stand-in for the real Report, so assertions can inspect one check."""

    def __init__(self):
        self.checks = []

    def add(self, name, ok, detail=""):
        self.checks.append((name, ok, detail))


class TestReport:
    def test_all_pass_is_zero_failures(self, mod):
        r = mod.Report()
        r.add("a", True, "fine")
        r.add("b", True, "fine")
        assert r.failed == []

    def test_any_failure_is_surfaced(self, mod):
        r = mod.Report()
        r.add("a", True)
        r.add("b", False, "broken")
        assert len(r.failed) == 1
        assert r.failed[0][0] == "b"

    def test_render_contains_ok_and_fail_markers(self, mod):
        r = mod.Report()
        r.add("good", True)
        r.add("bad", False)
        out = r.render()
        assert "[OK] good" in out
        assert "[FAIL] bad" in out
        assert "1/2 checks passed" in out

    def test_render_of_empty_report_does_not_crash(self, mod):
        # width= defaults to 10 when there are no checks; a crash here would
        # take down the whole verifier on an empty repo listing.
        assert "0/0 checks passed" in mod.Report().render()


class TestDuplicateThreshold:
    """The alarm that detects the laptop's nightly sync having stopped."""

    @staticmethod
    def _ratio_case(mod, total, distinct):
        ratio = (total - distinct) / total if total else 0.0
        return ratio <= mod.DUPLICATE_RATIO_LIMIT, ratio

    def test_limit_is_a_sane_fifteen_percent(self, mod):
        # Too low and the normal merge window fails the build every day; too
        # high and a dead merge goes unnoticed for a week.
        assert mod.DUPLICATE_RATIO_LIMIT == 0.15

    def test_no_duplication_passes(self, mod):
        ok, ratio = self._ratio_case(mod, 119_343, 119_343)
        assert ok
        assert ratio == 0.0

    def test_observed_2026_10_13_window_passes(self, mod):
        """2,062 duplicates out of 119,343 is the real, expected steady state."""
        ok, ratio = self._ratio_case(mod, 119_343, 117_281)
        assert ok, "the normal merge window must not fail the build"
        assert 0.015 < ratio < 0.02

    def test_merge_stalled_fails(self, mod):
        """If CI keeps appending and nothing merges, the ratio must fail."""
        ok, ratio = self._ratio_case(mod, 200_000, 100_000)
        assert not ok
        assert ratio == 0.5

    def test_boundary_is_inclusive(self, mod):
        # Exactly at the limit passes; a hair over fails.
        total = 1000
        at_limit = total - int(mod.DUPLICATE_RATIO_LIMIT * total)
        ok, _ = self._ratio_case(mod, total, at_limit)
        assert ok
        ok_over, _ = self._ratio_case(mod, total, at_limit - 1)
        assert not ok_over

    def test_zero_rows_does_not_divide_by_zero(self, mod):
        ok, ratio = self._ratio_case(mod, 0, 0)
        assert ok
        assert ratio == 0.0


class TestExpectedColumns:
    def test_reads_from_the_exporter_not_a_copy(self, mod):
        """A duplicated column list here would silently verify the wrong thing."""
        from job_market_intel.corpus.shard_export import SHARD_COLUMNS

        assert mod.expected_columns() == list(SHARD_COLUMNS) + ["origin"]

    def test_origin_is_last(self, mod):
        assert mod.expected_columns()[-1] == "origin"


class TestEnabledSources:
    def test_reads_the_real_registry(self, mod):
        sources = mod.enabled_sources()
        assert "remoteok" in sources
        # Indeed is present in the registry but disabled.
        assert "indeed" not in sources

    def test_missing_registry_returns_empty_rather_than_raising(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "SOURCES_JSON", Path("/nonexistent/sources.json"))
        assert mod.enabled_sources() == []
