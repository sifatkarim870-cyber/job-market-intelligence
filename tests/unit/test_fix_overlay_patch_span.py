"""The patcher must replace upload_overlay's body and NOTHING else.

Three separate incidents came from the same mistake: locating the end of a
function by scanning text for the next ``def`` at column 0.

1. Stopping on any line starting with ``# `` ran past the boundary and deleted
   ``main()``. The kernel then failed with ``NameError: name 'main' is not
   defined`` after a full seven-minute run.
2. Stopping at the next column-0 ``def``/``class`` deleted the module-level
   ``CANDIDATE_LABELS = (...)`` assignment, which sits BETWEEN
   ``upload_overlay`` and ``find_token`` in that notebook. ``find_token``
   iterates the tuple, so the kernel would have died with a NameError on its
   next scheduled run. An assignment is not a ``def``; any text scan that stops
   at one is wrong.
3. Referencing ``CANDIDATE_LABELS`` in ``find_token`` while defining it only in
   the patching script -- the kernel runs standalone, so it had no constant at
   all, and the run died on its final line.

The fix is to locate the span with AST ``end_lineno`` and then assert that no
module-level name disappeared. These tests pin that behaviour against a
realistic cell that reproduces the exact layout.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fix_overlay_overwrite.py"


@pytest.fixture(scope="module")
def patcher():
    spec = importlib.util.spec_from_file_location("fix_overlay_overwrite", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: Mirrors the real notebook layout: the constant sits between the two
#: functions, which is exactly what a column-0 ``def`` scan eats.
CELL = '''import pathlib

WORK = pathlib.Path("/kaggle/working")
OVERLAY_REPO_ID = "owner/repo"


def upload_overlay(con, rows):
    """Old destructive body."""
    return len(rows)


#: Secret labels tried in order by find_token.
CANDIDATE_LABELS = ("hf_token.txt", "hf_token")


def find_token():
    for label in CANDIDATE_LABELS:
        return label
    raise SystemExit("no token")


def main():
    return upload_overlay(None, [])
'''


def notebook(cells: list[str], tmp_path: Path) -> Path:
    path = tmp_path / "kernel.ipynb"
    path.write_text(
        json.dumps(
            {
                "cells": [
                    {"cell_type": "code", "source": [c], "metadata": {}, "outputs": []}
                    for c in cells
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )
    return path


def code_of(path: Path) -> str:
    return "\n".join(
        "".join(c["source"]) for c in json.loads(path.read_text(encoding="utf-8"))["cells"]
    )


def test_patch_preserves_every_module_level_name(patcher, tmp_path: Path) -> None:
    path = notebook([CELL], tmp_path)
    before = patcher.top_level_names(CELL)

    assert patcher.patch(path) is True

    after = patcher.top_level_names(code_of(path))
    assert before - after == set(), f"patch deleted {sorted(before - after)}"


def test_patch_keeps_candidate_labels(patcher, tmp_path: Path) -> None:
    """The exact regression: CANDIDATE_LABELS lived between the two defs."""
    path = notebook([CELL], tmp_path)
    patcher.patch(path)

    src = code_of(path)
    assert "CANDIDATE_LABELS = " in src
    assert "CANDIDATE_LABELS" in patcher.top_level_names(src)


def test_patch_keeps_sibling_functions(patcher, tmp_path: Path) -> None:
    path = notebook([CELL], tmp_path)
    patcher.patch(path)

    funcs = patcher.top_level_names(code_of(path))
    assert {"upload_overlay", "find_token", "main"} <= funcs


def test_patched_cell_still_compiles(patcher, tmp_path: Path) -> None:
    path = notebook([CELL], tmp_path)
    patcher.patch(path)
    compile(code_of(path), "cell", "exec")


def test_top_level_names_finds_functions_and_assignments(patcher) -> None:
    assert patcher.top_level_names(CELL) >= {
        "upload_overlay",
        "find_token",
        "main",
        "CANDIDATE_LABELS",
        "WORK",
        "OVERLAY_REPO_ID",
    }


def test_module_constant_is_self_contained(patcher) -> None:
    """The constant must be defined by the notebook, not by this script.

    find_token references it at runtime on Kaggle, where this module does not
    exist. Shipping the tuple only here cost a seven-minute run.
    """
    const = patcher.LABELS_CONST
    compile(const, "const", "exec")
    assert "CANDIDATE_LABELS = " in const
