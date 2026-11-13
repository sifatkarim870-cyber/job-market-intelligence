"""Shared exit-code contract for scraper runners.

Every ``scripts/run_<source>_scraper.py`` used to end with ``return 0``. A run
that fetched nothing, persisted nothing, or failed validation was therefore
indistinguishable from a healthy one -- the failure class the CI quality gate
was built to catch.

The contract is deliberately narrow, because the first version of this guard
was too broad and would have painted healthy degraded feeds red:

* a dry run (``--no-db``) always exits 0;
* any per-row persistence failure exits 1;
* a run that persisted no rows (inserted + updated + unchanged) exits 1 --
  this is also the case a failed batch validation catches;
* a validation failure with rows persisted stays green: a board that returned
  15 of 25 postings and stored 14 is a working scraper on a quiet board, not a
  broken one. Only the zero-row case is breakage.

A partially failed run still exits 1, but its persisted rows are not lost: the
scrape workflows export under ``if: always()`` after checking that the source
wrote at least one row.
"""

from __future__ import annotations

from typing import Any

#: Result fields that count as "this row is in the database". ``unchanged`` is
#: included on purpose: re-scraping a known posting is a successful observation,
#: not an empty run.
_PERSISTED_FIELDS = ("inserted_count", "updated_count", "unchanged_count", "persisted_count")

#: Result fields that count as "this row did not make it".
_FAILED_FIELDS = ("failed_count", "persistence_failures")


def _value(result: Any, field: str, default: int = 0) -> int:
    if isinstance(result, dict):
        raw = result.get(field, default)
    else:
        raw = getattr(result, field, default)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return default


def persisted_rows(result: Any) -> int:
    """Rows the run observed in the database (inserted + updated + unchanged)."""
    return sum(_value(result, field) for field in _PERSISTED_FIELDS)


def failed_rows(result: Any) -> int:
    """Rows that raised during persistence."""
    return sum(_value(result, field) for field in _FAILED_FIELDS)


def runner_exit_code(result: Any, *, store_db: bool) -> int:
    """Exit code for one scraper run.

    ``result`` may be a single run-result object, a dict, or a list of them
    (Indeed processes a queue and returns one result per claimed job).
    """
    if not store_db:
        return 0

    results = list(result) if isinstance(result, (list, tuple)) else [result]
    if not results:
        return 1

    if any(failed_rows(r) > 0 for r in results):
        return 1
    if sum(persisted_rows(r) for r in results) == 0:
        return 1
    return 0
