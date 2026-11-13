"""Every scraper runner must exit non-zero when a run stored nothing.

Discovered 2026-10-18 on Vagas.com.br. After aggressive probing the site returned
HTTP 429 for every request and the run reported::

    Postings fetched: 45   Fetch failures: 45   Parsed: 0   Inserted: 0
    Batch validation: FAILED

and **exited 0**. In CI that is a green tick on a source that stored nothing --
indistinguishable from success by reading the tick.

The rule is deliberately narrow. Over-broad failure exits break healthy
degraded feeds: a run that fetches 15 of 25 and inserts 14 is a working scraper
on a quiet board, and must stay green. Only ``persisted == 0`` or a per-row
persistence failure is breakage.

This file now tests the shared contract in ``common.runner`` and asserts every
runner uses it, instead of checking literal guard strings in three files.
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass

import pytest

from job_market_intel.common.runner import runner_exit_code

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNNERS = sorted((REPO / "scripts").glob("run_*_scraper.py"))


@dataclass
class _Result:
    inserted_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    failed_count: int = 0
    validation_passed: bool = True


def test_dry_run_is_always_green() -> None:
    assert runner_exit_code(_Result(), store_db=False) == 0
    assert runner_exit_code(None, store_db=False) == 0


def test_a_zero_yield_failed_validation_is_red() -> None:
    """The exact Vagas.com.br case: 45 fetched, 45 failed, 0 inserted."""
    assert runner_exit_code(_Result(validation_passed=False), store_db=True) == 1


def test_a_degraded_but_productive_run_stays_green() -> None:
    """14 stored out of 25 fetched is a quiet board, not a broken scraper."""
    assert (
        runner_exit_code(
            _Result(inserted_count=14, validation_passed=False),
            store_db=True,
        )
        == 0
    )


def test_unchanged_rows_count_as_persisted() -> None:
    """Re-scraping known postings is a successful observation."""
    assert runner_exit_code(_Result(unchanged_count=5), store_db=True) == 0


def test_any_persistence_failure_is_red() -> None:
    assert runner_exit_code(_Result(inserted_count=3, failed_count=1), store_db=True) == 1


def test_list_of_results_aggregates() -> None:
    assert runner_exit_code([_Result(inserted_count=1), _Result(unchanged_count=2)], store_db=True) == 0
    assert runner_exit_code([_Result(inserted_count=1), _Result(failed_count=1)], store_db=True) == 1
    assert runner_exit_code([], store_db=True) == 1


def test_dict_result_is_supported() -> None:
    assert runner_exit_code({"inserted_count": 2}, store_db=True) == 0
    assert runner_exit_code({"inserted_count": 0}, store_db=True) == 1


@pytest.mark.parametrize("rel", RUNNERS, ids=lambda p: p.name)
def test_every_runner_uses_the_shared_contract(rel: pathlib.Path) -> None:
    """A rule enforced on three of fifty-two runners is not a convention."""
    src = rel.read_text(encoding="utf-8")
    assert "runner_exit_code" in src, f"{rel.name} has no shared exit contract"

    tree = ast.parse(src)
    main = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    assert "runner_exit_code" in ast.dump(main), f"{rel.name}: contract not reached from main()"


@pytest.mark.parametrize("rel", RUNNERS, ids=lambda p: p.name)
def test_runner_is_syntactically_valid(rel: pathlib.Path) -> None:
    ast.parse(rel.read_text(encoding="utf-8"))
