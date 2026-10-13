"""The port must not silently revert the scheduled kernel's token lookup.

The landmine
------------
``build()`` copies the source notebook (``jmi-translate-hf``) onto the target's
identity wholesale. The two kernels do not agree on how to obtain the HF token:

* ``jmi-translate-hf`` still uses the file scan
  ``for p in pathlib.Path("/kaggle").rglob("*.txt")``
* ``nllb-translate`` asks for the secret by name via ``UserSecretsClient``

Kaggle serves secrets through ``UserSecretsClient``; it does not mount them as
readable files. The scan therefore finds nothing and failed on eight consecutive
scheduled runs before it was replaced. Copying the source notebook verbatim puts
the scheduled kernel straight back into that state, with no error at push time --
the failure only appears hours later, on a schedule.

These tests pin the behaviour: the target's working lookup survives the copy.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "port_kaggle_kernel_to_hf.py"


@pytest.fixture(scope="module")
def porter():
    spec = importlib.util.spec_from_file_location("port_kaggle_kernel_to_hf", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The source kernel's token lookup: the file scan that cannot work.
SOURCE = '''import pathlib


def log(msg):
    print(msg)


def find_token():
    for p in pathlib.Path("/kaggle").rglob("*.txt"):
        t = p.read_text().strip()
        if t.startswith("hf_") and len(t) > 20:
            return t
    raise SystemExit("no HF token found")


def open_corpus():
    return "con"


def run_gpu(rows):
    return [], {}


def upload_overlay(con, rows):
    from huggingface_hub import HfApi, hf_hub_download
    return len(rows)


def main():
    return upload_overlay(None, [])
'''

#: The scheduled kernel's working lookup, plus the constant it iterates.
TARGET = '''from __future__ import annotations

import pathlib

CANDIDATE_LABELS = ("hf_token.txt", "hf_token")


def log(msg):
    print(msg)


def open_corpus():
    return "con"


def run_gpu(rows):
    return [], {}


def find_token():
    from kaggle_secrets import UserSecretsClient

    client = UserSecretsClient()
    for label in CANDIDATE_LABELS:
        token = (client.get_secret(label) or "").strip()
        if token.startswith("hf_"):
            return token
    raise SystemExit("no HF token found")


def upload_overlay(con, rows):
    from huggingface_hub import HfApi, hf_hub_download
    return len(rows)


def main():
    return upload_overlay(None, [])
'''


def test_code_of_reads_cells_not_json(porter, tmp_path: Path) -> None:
    """A notebook's JSON contains no find_token; only its code does."""
    nb = {
        "cells": [
            {"cell_type": "code", "source": ["def find_token():\n", "    return 1\n"]}
        ],
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path = tmp_path / "k.ipynb"
    path.write_text(__import__("json").dumps(nb), encoding="utf-8")
    assert "def find_token" in porter.code_of(path)


def test_port_carries_the_targets_token_lookup(porter) -> None:
    ported, notes = porter.carry_token_lookup(SOURCE, TARGET)
    assert "UserSecretsClient" in ported
    assert 'rglob("*.txt")' not in ported
    assert any("find_token" in n for n in notes)


def test_port_keeps_candidate_labels_constant(porter) -> None:
    """find_token iterates the tuple; without it the kernel raises NameError."""
    ported, notes = porter.carry_token_lookup(SOURCE, TARGET)
    assert "CANDIDATE_LABELS = " in ported
    assert any("CANDIDATE_LABELS" in n for n in notes)


def test_ported_notebook_compiles_and_keeps_functions(porter) -> None:
    ported, _ = porter.carry_token_lookup(SOURCE, TARGET)
    compile(ported, "ported", "exec")
    import ast

    funcs = {n.name for n in ast.parse(ported).body if isinstance(n, ast.FunctionDef)}
    assert {"find_token", "upload_overlay", "main"} <= funcs


def test_ported_notebook_passes_verification(porter) -> None:
    ported, _ = porter.carry_token_lookup(SOURCE, TARGET)
    porter.verify_ported(ported)  # must not raise


def test_verification_rejects_a_reverted_file_scan(porter) -> None:
    """The unrepaired port -- exactly what the script used to produce."""
    with pytest.raises(SystemExit, match=r"\*\.txt"):
        porter.verify_ported(SOURCE)


def test_verification_ignores_prose_mentioning_a_broken_api(porter) -> None:
    """The merge's docstring explains download_repo_file in prose.

    A substring check flags that fixed, working code as broken, which is how a
    correct port was rejected once already.
    """
    ported, _ = porter.carry_token_lookup(SOURCE, TARGET)
    documented = ported.replace(
        "def upload_overlay(con, rows):",
        'def upload_overlay(con, rows):\n    """Earlier used HfApi.download_repo_file."""',
        1,
    )
    porter.verify_ported(documented)  # must not raise


def test_verification_rejects_a_real_download_repo_file_call(porter) -> None:
    broken = SOURCE.replace(
        "def upload_overlay(con, rows):\n    from huggingface_hub import HfApi, hf_hub_download",
        "def upload_overlay(con, rows):\n    from huggingface_hub import HfApi\n"
        "    return HfApi().download_repo_file('r', 'f')",
    )
    with pytest.raises(SystemExit, match="download_repo_file"):
        porter.verify_ported(broken)
