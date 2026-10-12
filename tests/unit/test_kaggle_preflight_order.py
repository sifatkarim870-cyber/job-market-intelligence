"""The token preflight must run before any expensive work, and that is an
ordering property, not a presence property.

The bug
-------
``main()`` opened the corpus, logged, ran the model smoke test and entered the
translation loop. ``find_token()`` was first reached inside
``upload_overlay()``, which is only called at the first checkpoint -- after five
batches of translation. A run with no usable secret therefore loaded the NLLB
weights, translated for as long as it could, and then raised::

    SystemExit: no HF token found. Tried UserSecretsClient labels ...

and discarded every row, because the only call that could have persisted them
was the one that failed. Measured directly: a run burned 1807s and produced
nothing. After the fix the same push finished in ~90s with no model load.

These tests assert the call ORDER inside ``main``. A test that merely checked
``find_token`` appears somewhere would pass against the broken version.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "patch_kaggle_preflight.py"


@pytest.fixture(scope="module")
def patcher():
    spec = importlib.util.spec_from_file_location("patch_kaggle_preflight", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main_body(source: str) -> str:
    """The text of ``main()``, where call order is readable."""
    return source[source.index("def main():") :]


#: Shaped like the real kernel: token resolution used to live only inside
#: upload_overlay, which the checkpoint reaches after five batches.
CELL = '''import json

import torch

WORK = None
CORPUS_REPO_ID = "owner/corpus"
OVERLAY_REPO_ID = "owner/overlay"
CANDIDATE_LABELS = ("hf_token.txt", "hf_token")
state = {"errors": [], "started": 0}


def log(msg):
    print(msg)


def report(name, payload=None):
    pass


def open_corpus():
    return "con"


def fetch_pending(con, offset):
    return []


def run_gpu(rows):
    return [], {}


def upload_overlay(con, rows):
    from huggingface_hub import hf_hub_download

    token = find_token()
    return len(rows)


def find_token():
    from kaggle_secrets import UserSecretsClient

    client = UserSecretsClient()
    return client.get_secret(CANDIDATE_LABELS[0])


def main():
    import duckdb
    con = open_corpus()
    info = {"torch": torch.__version__, "gpus": torch.cuda.device_count()}
    report("start", info)
    log(json.dumps(info))
    overlay = []
    batches = 0
    while True:
        batch = fetch_pending(con, 0)
        if not batch:
            break
        batches += 1
        if batches % 5 == 0:
            upload_overlay(con, overlay)
    upload_overlay(con, overlay)
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


def test_unpatched_kernel_resolves_the_token_too_late() -> None:
    """States the regression, so the ordering test below has a meaning."""
    body = main_body(CELL)
    assert "find_token()" not in body
    # ...it is only reached via upload_overlay, after five batches.
    assert body.index("upload_overlay(con, overlay)") > body.index("open_corpus()")


def test_preflight_runs_before_the_corpus_is_opened(patcher, tmp_path: Path) -> None:
    path = notebook([CELL], tmp_path)
    applied = patcher.patch(path)
    assert len(applied) == 2

    body = main_body(code_of(path))
    assert body.index("find_token()") < body.index("open_corpus()")


def test_preflight_runs_before_the_model_is_loaded(patcher, tmp_path: Path) -> None:
    path = notebook([CELL], tmp_path)
    patcher.patch(path)
    src = code_of(path)

    main = next(
        n
        for n in ast.parse(src).body
        if isinstance(n, ast.FunctionDef) and n.name == "main"
    )
    calls = [
        c.func.id
        for c in ast.walk(main)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
    ]
    assert calls[0] == "find_token", f"first call in main() was {calls[0]!r}, not find_token"


def test_preflight_is_idempotent(patcher, tmp_path: Path) -> None:
    path = notebook([CELL], tmp_path)
    patcher.patch(path)
    assert patcher.patch(path) == [], "re-patching inserted the preflight twice"


def test_gpu_warning_is_added_but_does_not_exit(patcher, tmp_path: Path) -> None:
    """A CPU run is legitimate; it must warn, not abort."""
    path = notebook([CELL], tmp_path)
    patcher.patch(path)
    src = code_of(path)

    assert "no GPU allocated" in src
    warn_start = src.index("if info[\"gpus\"] == 0")
    warn_end = src.index("log(\"WARNING", warn_start)
    block = src[warn_start:warn_end]
    assert "raise" not in block and "sys.exit" not in block


def test_verify_rejects_a_reverted_preflight(patcher, tmp_path: Path) -> None:
    """The guard must fail if find_token is moved back after open_corpus."""
    path = notebook([CELL], tmp_path)
    patcher.patch(path)
    good = code_of(path)

    reordered = good.replace("    find_token()\n", "", 1)
    reordered = reordered.replace(
        "    con = open_corpus()\n", "    con = open_corpus()\n    find_token()\n", 1
    )
    with pytest.raises(SystemExit, match="preflight still runs after"):
        patcher.verify(reordered)


def test_patch_preserves_module_level_names(patcher, tmp_path: Path) -> None:
    path = notebook([CELL], tmp_path)
    before = patcher.top_level_names(CELL)
    patcher.patch(path)
    after = patcher.top_level_names(code_of(path))
    assert before - after == set()
