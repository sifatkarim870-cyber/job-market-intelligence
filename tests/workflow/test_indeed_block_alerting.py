"""Runs the bash behavioural tests for the workflow's Indeed block-alerting step.

The alerting logic lives in shell inside .github/workflows/scrape.yml, so it is
tested by executing it. This wrapper exists so `pytest` picks the suite up and
so it degrades honestly: a machine without bash (a stock Windows dev box, or a
Python-only container) skips rather than fails, because the logic it guards is
still verified on the Linux runner where the workflow actually executes.

See tests/workflow/indeed_block_alerting.sh for what these cases cover and why
they exist.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_HARNESS = Path(__file__).parent / "indeed_block_alerting.sh"
_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available on this platform")
def test_indeed_block_alerting_step_behaves() -> None:
    # PY is the interpreter the harness uses to read the workflow YAML and the
    # JSON counters; sys.executable guarantees one with PyYAML installed.
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["bash", str(_HARNESS)],
        cwd=_REPO_ROOT,
        env={**os.environ, "PY": sys.executable},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"block-alerting harness failed\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
