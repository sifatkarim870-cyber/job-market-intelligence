#!/usr/bin/env python
"""
verify_env.py — sanity-check that the local development environment is
correctly configured.

Checks performed:
    1. Python version meets the project's minimum (>=3.11).
    2. Required top-level directories exist.
    3. `.env` exists (warns, does not fail, if missing).
    4. Base configuration loads and validates successfully
       (job_market_intel.common.config.get_settings()).

This script intentionally does NOT attempt a real database connection —
that belongs to Step 4 (Build the Database Interface), once the DB layer
exists. It only confirms the *environment* is sound.

Usage:
    uv run python scripts/verify_env.py
"""

from __future__ import annotations

import sys
from pathlib import Path

MIN_PYTHON = (3, 11)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DIRS = [
    "src/job_market_intel",
    "tests/unit",
    "tests/integration",
    "logs/scrapers",
    "logs/database",
    "logs/api",
    "logs/scheduler",
    "logs/system",
    "docs",
    "seed",
]

# Make `src/` importable when running this script directly (uv run handles
# this automatically once the package is installed in editable mode via
# `uv sync`, but we defend against ad hoc `python scripts/verify_env.py`).
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "OK  " if ok else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    print("Job Market Intelligence Platform — environment verification\n")
    all_ok = True

    # 1. Python version
    current = sys.version_info[:2]
    ok = current >= MIN_PYTHON
    all_ok &= check(
        f"Python version >= {'.'.join(map(str, MIN_PYTHON))}",
        ok,
        f"found {'.'.join(map(str, current))}",
    )

    # 2. Required directories
    print("\n  Directory structure:")
    for rel_dir in REQUIRED_DIRS:
        path = PROJECT_ROOT / rel_dir
        ok = path.is_dir()
        all_ok &= check(rel_dir, ok)

    # 3. .env presence (warning only, not fatal)
    print("\n  Environment file:")
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        check(".env exists", True)
    else:
        print("  [WARN]  .env not found — copy .env.example to .env and fill in values.")

    # 4. Configuration loads
    print("\n  Configuration:")
    try:
        from job_market_intel.common.config import get_settings

        settings = get_settings()
        check("Base configuration loads and validates", True, f"app_env={settings.app_env}")
    except SystemExit as exc:
        check("Base configuration loads and validates", False, str(exc).splitlines()[0])
        all_ok = False
    except Exception as exc:  # noqa: BLE001 — top-level diagnostic script
        check("Base configuration loads and validates", False, f"unexpected error: {exc}")
        all_ok = False

    print()
    if all_ok:
        print("Environment looks good.")
        return 0
    else:
        print("One or more checks failed — see above.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
