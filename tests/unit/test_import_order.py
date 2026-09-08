"""Regression guard against import-order-dependent circular imports.

Why this test exists (Step 14): ``job_market_intel.validation.remoteok_validator``
used to import ``RawRemoteOKJob`` from ``scrapers.remoteok.models`` at
module level. That created a real circular import between the
``validation`` and ``scrapers.remoteok`` packages
(``scrapers.remoteok.__init__`` -> ``.pipeline`` -> ``validation`` ->
``remoteok_validator`` -> ``scrapers.remoteok.models``, which forces
``scrapers.remoteok.__init__`` to still be mid-execution) that only
surfaced depending on which package got imported *first* — every existing
test happened to import ``scrapers.remoteok`` (directly or transitively)
before ``validation``, so the whole suite passed while a plain
``import job_market_intel.validation`` as someone's very first line would
have crashed. See ``validation/remoteok_validator.py``'s module docstring
for the fix (a ``TYPE_CHECKING``-guarded import).

Each check below runs in a genuinely fresh Python subprocess (not just a
fresh import inside the same pytest session) specifically because Python
caches modules in ``sys.modules`` — once any earlier test or fixture has
imported a module, re-importing it here would silently reuse the cached,
already-initialized version and could never reproduce an import-order bug,
no matter how the import is written in this file. As more sources are
added (Step 14's shared modules are exactly the pattern every future
source's validator/cleaner will follow), this guards against the same
class of bug reappearing between ``cleaning``/``validation`` and any of
them.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

#: Every top-level subpackage that should be importable completely on its
#: own, in a fresh interpreter, regardless of what (if anything) has been
#: imported before it. Add a new source's ``scrapers.<source>`` here once
#: it exists.
_INDEPENDENTLY_IMPORTABLE_MODULES = [
    "job_market_intel.validation",
    "job_market_intel.cleaning",
    "job_market_intel.scrapers.remoteok",
    "job_market_intel.db.job_repository",
    "job_market_intel.normalization",
]


def _run_fresh_import(*module_names: str) -> subprocess.CompletedProcess[str]:
    """Import the given modules, in order, in a brand-new subprocess."""
    code = "\n".join(f"import {name}" for name in module_names)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestEachPackageImportsStandalone:
    @pytest.mark.parametrize("module_name", _INDEPENDENTLY_IMPORTABLE_MODULES)
    def test_module_imports_alone_in_a_fresh_interpreter(self, module_name: str) -> None:
        result = _run_fresh_import(module_name)
        assert result.returncode == 0, (
            f"`import {module_name}` failed as the first import in a fresh "
            f"interpreter:\n{result.stderr}"
        )


class TestValidationAndScrapersRemoteokImportOrderIndependence:
    """The specific pair that used to be order-dependent."""

    def test_validation_before_scrapers_remoteok(self) -> None:
        result = _run_fresh_import(
            "job_market_intel.validation", "job_market_intel.scrapers.remoteok"
        )
        assert result.returncode == 0, result.stderr

    def test_scrapers_remoteok_before_validation(self) -> None:
        result = _run_fresh_import(
            "job_market_intel.scrapers.remoteok", "job_market_intel.validation"
        )
        assert result.returncode == 0, result.stderr

    def test_cleaning_before_scrapers_remoteok(self) -> None:
        result = _run_fresh_import(
            "job_market_intel.cleaning", "job_market_intel.scrapers.remoteok"
        )
        assert result.returncode == 0, result.stderr

    def test_all_four_together_regardless_of_order(self) -> None:
        result = _run_fresh_import(
            "job_market_intel.db.job_repository",
            "job_market_intel.validation",
            "job_market_intel.cleaning",
            "job_market_intel.scrapers.remoteok",
        )
        assert result.returncode == 0, result.stderr


class TestNormalizationImportOrderIndependence:
    """normalization.dedup only depends on sqlalchemy.orm.Session (passed in
    by the caller) and its own config module -- not on db.job_repository or
    any scraper package -- so it should be importable in any order relative
    to them. Added alongside Step 19 (Cross-Source Duplicate Detection).
    """

    def test_normalization_before_db_job_repository(self) -> None:
        result = _run_fresh_import(
            "job_market_intel.normalization", "job_market_intel.db.job_repository"
        )
        assert result.returncode == 0, result.stderr

    def test_db_job_repository_before_normalization(self) -> None:
        result = _run_fresh_import(
            "job_market_intel.db.job_repository", "job_market_intel.normalization"
        )
        assert result.returncode == 0, result.stderr
