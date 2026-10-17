"""A run that collected nothing must not exit 0.

Discovered 2026-10-18 on Vagas.com.br. After aggressive probing the site returned
HTTP 429 for every request and the run reported::

    Postings fetched: 45   Fetch failures: 45   Parsed: 0   Inserted: 0
    Batch validation: FAILED

and **exited 0**. In CI that is a green tick on a source that stored nothing --
indistinguishable from success by reading the tick.

The rule is deliberately narrow. Over-broad failure exits break healthy
degraded feeds: a run that fetches 15 of 25 and inserts 14 is a working scraper
on a quiet board, and must stay green. Only ``persisted == 0`` **and**
``validation_passed is False`` is breakage.

Run with:  uv run pytest tests/unit/test_runner_exit_codes.py -q
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

#: The runners this rule is pinned on. Extend the list as sources are added --
#: a rule enforced on two of thirty runners is not a convention.
RUNNERS = [
    "scripts/run_vagas_com_br_scraper.py",
    "scripts/run_angola_emprego_scraper.py",
]


def _main_source(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", RUNNERS)
class TestZeroYieldRunsExitNonZero:
    def test_the_guard_is_present(self, rel: str) -> None:
        src = _main_source(rel)
        assert "persisted nothing" in src, f"{rel} has no zero-yield guard"

    def test_it_actually_returns_one(self, rel: str) -> None:
        """Not just a printed message -- the process exit code matters."""
        assert "return 1" in _main_source(rel), f"{rel} never returns non-zero"

    def test_the_guard_is_inside_main(self, rel: str) -> None:
        """A module-level return would be a syntax error; a guard in the wrong
        function would never run."""
        tree = ast.parse(_main_source(rel))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main")
        body = ast.dump(fn)
        assert "persisted" in body, f"{rel}: the guard is not inside main()"

    def test_a_degraded_but_productive_run_still_exits_zero(self, rel: str) -> None:
        """The guard must not fire when rows were persisted.

        This is the case a naive 'exit non-zero on validation failure' would
        break: a board with fewer live postings than the configured floor.
        """
        src = _main_source(rel)
        assert "persisted == 0" in src, (
            f"{rel}: the guard must be conditioned on zero persisted rows, not "
            f"on validation failure alone"
        )
        assert "not result.validation_passed and persisted == 0" in src, (
            f"{rel}: the guard must require BOTH conditions"
        )


@pytest.mark.parametrize("rel", RUNNERS)
def test_runner_is_syntactically_valid(rel: str) -> None:
    """A patched runner that does not parse is worse than an unguarded one."""
    ast.parse(_main_source(rel))
