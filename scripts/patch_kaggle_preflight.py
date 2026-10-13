"""Fail fast on a missing token, and make GPU allocation legible.

1. The token is resolved too late
--------------------------------
``main()`` opened the corpus, logged, ran the model smoke test, and then entered
the translation loop. ``find_token()`` was first reached inside
``upload_overlay()``, which is only called at the first checkpoint -- after five
batches of translation. So a run without a usable secret spent the whole run
translating and then raised::

    SystemExit: no HF token found. Tried UserSecretsClient labels ...

discarding every row it had produced. Observed directly: a run reached 1807s,
translated, then failed at ``upload_overlay -> find_token``. The work was
unrecoverable because the only place it could have been written was the call
that failed.

The token is now resolved first thing, before the corpus is opened and before
the model is loaded. A missing secret then costs about two seconds instead of
the entire run.

2. A silent CPU fallback
------------------------
``enable_gpu`` is ``true`` in ``kernel-metadata.json`` for both kernels, and
the metadata is otherwise identical between them. Yet runs have logged::

    [8s] {"torch": "2.11.0+cpu", "gpus": 0}

That is not a misconfiguration -- ``torch`` is chosen before any user code
runs, so a ``+cpu`` build means Kaggle allocated no GPU slot to that run. It is
observable rather than controllable: the same kernel later ran with
``{"torch": "2.11.0+cu128", "gpus": 2}`` after sitting in ``QUEUED``.

Because it is a queue effect and not a setting, the useful change is to say so
out loud. A CPU run is legitimate and still publishes, but it is orders of
magnitude slower and may hit the time cap, and "gpus: 0" in a JSON line is easy
to miss when scanning a log.

What this does NOT do
---------------------
It does not force, request or retry a GPU, and it does not exit when
``gpus == 0``. A CPU run is a valid run; aborting it would throw away work that
a drained corpus completes in minutes. It warns instead.

Usage:
    python scripts/patch_kaggle_preflight.py
    python scripts/patch_kaggle_preflight.py --push
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

KERNEL = "mskarim870/nllb-translate"
HEAD = "def main():"

PREFIX = """    # Resolve the token BEFORE any expensive work. find_token() is otherwise
    # first reached inside upload_overlay(), which runs only at the first
    # checkpoint -- after five batches of translation. A run without a usable
    # secret therefore loaded the model, translated for as long as it could,
    # and then raised SystemExit and discarded every row. Two runs were lost
    # this way, one after 1807s of work. A token failure must cost seconds.
    find_token()
    log("token resolved before starting")

"""

GPU_WARNING = """    if info["gpus"] == 0:
        # enable_gpu is true in kernel-metadata.json, so 0 here means Kaggle
        # allocated no GPU slot, not that GPU was switched off. torch is
        # resolved before any user code runs, so a +cpu build proves it. This
        # is a queue effect: the same kernel later ran with
        # {"torch": "2.11.0+cu128", "gpus": 2} straight after sitting QUEUED.
        # The run still completes and still publishes -- it is just far slower
        # and may reach the time cap first -- so this warns rather than exits.
        log("WARNING: no GPU allocated although enable_gpu=true. Kaggle "
            "assigned no slot; translation will run on CPU.")
"""

ANCHOR = "    log(json.dumps(info))\n"


def kaggle(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "kaggle", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def code_of(nb: dict) -> str:
    return "\n".join(
        "".join(c["source"]) for c in nb.get("cells", []) if c.get("cell_type") == "code"
    )


def top_level_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def patch(nb_path: pathlib.Path) -> list[str]:
    """Insert the token preflight and the GPU warning into ``main``.

    Insertion points come from AST line numbers, never from a text scan for the
    next ``def``/``class``. Three earlier patches used text scans and each one
    destroyed neighbouring code: a ``# `` boundary deleted ``main()``, a
    column-0 ``def`` boundary deleted the ``CANDIDATE_LABELS`` assignment, and a
    loose substring match deleted ``WORK``.
    """
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    applied: list[str] = []

    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell["source"])
        if HEAD not in source:
            continue

        before = top_level_names(source)
        if "token resolved before starting" in source:
            print("   preflight already present; nothing to do")
            return []

        lines = source.splitlines(keepends=True)
        tree = ast.parse(source)
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        first = main.body[0]
        # 1-based lineno of main's first statement -> 0-based insert index.
        at = first.lineno - 1
        lines.insert(at, PREFIX)
        source = "".join(lines)

        if ANCHOR not in source:
            raise SystemExit("could not find the info log anchor inside main()")
        source = source.replace(ANCHOR, ANCHOR + GPU_WARNING, 1)
        applied.append("token preflight before any translation work")
        applied.append("explicit warning when no GPU slot is allocated")

        compile(source, "cell", "exec")
        after = top_level_names(source)
        if lost := before - after:
            raise SystemExit(f"patch would delete top-level names {sorted(lost)}")

        cell["source"] = [source]

    if applied:
        nb_path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    return applied


def call_line(main: ast.FunctionDef, name: str) -> int:
    """1-based line of the first real call to ``name`` inside ``main``.

    Located with AST rather than ``str.index``, because the explanatory comment
    inserted above the preflight contains the literal text ``find_token()``. A
    substring search finds that prose first and then reports the ordering as
    correct even when the call has been moved back below ``open_corpus()`` --
    which is exactly what happened while testing this function.
    """
    for node in ast.walk(main):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name:
            return node.lineno
    raise SystemExit(f"{name}() is never called inside main()")


def verify(src: str) -> None:
    """Refuse to push unless the preflight really runs first.

    Checked by position, not by presence: ``find_token()`` appearing anywhere in
    main() is not the fix, it appearing before open_corpus() is. That ordering is
    the entire point.
    """
    for required in (
        "token resolved before starting",
        "no GPU allocated",
        "CANDIDATE_LABELS = ",
        "UserSecretsClient",
        "hf_hub_download",
    ):
        if required not in src:
            raise SystemExit(f"post-patch verification failed: {required!r} missing")
    if "NEON_DATABASE_URL" in src:
        raise SystemExit("notebook still references Neon")

    funcs = [n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)]
    main = next((n for n in funcs if n.name == "main"), None)
    if main is None:
        raise SystemExit("notebook has no main()")
    token_at = call_line(main, "find_token")
    corpus_at = call_line(main, "open_corpus")
    if token_at > corpus_at:
        raise SystemExit(
            f"preflight still runs after open_corpus() "
            f"(find_token line {token_at}, open_corpus line {corpus_at}); "
            "the fix is void"
        )
    print(f"sanity: compiles, {len(funcs)} functions intact, no Neon")
    print(
        f"        find_token() at line {token_at}, open_corpus() at line {corpus_at} "
        "(preflight first)"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kernel", default=KERNEL)
    ap.add_argument("--push", action="store_true", help="upload AND run (default: dry run)")
    ap.add_argument("--timeout", type=int, default=2400)
    args = ap.parse_args(argv)

    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_pre_"))
    result = kaggle("kernels", "pull", args.kernel, "-p", str(work), "-m")
    if result.returncode != 0:
        raise SystemExit(f"pull failed: {result.stderr.strip()[:300]}")

    nb = list(work.glob("*.ipynb"))[0]
    shutil.copyfile(nb, nb.with_suffix(".ipynb.bak"))
    print(f"pulled {args.kernel} -> {nb.name} ({nb.stat().st_size:,} bytes)")

    applied = patch(nb)
    if not applied:
        return 0
    for item in applied:
        print(f"   - {item}")

    src = code_of(json.loads(nb.read_text(encoding="utf-8")))
    verify(src)

    if not args.push:
        print("\n--dry run (default): nothing uploaded.")
        return 0

    print("\npushing (uploads AND runs)")
    result = kaggle("kernels", "push", "-p", str(work), "-t", str(args.timeout))
    print(f"   exit={result.returncode}")
    for stream in (result.stdout, result.stderr):
        for line in stream.splitlines():
            if line.strip():
                print(f"   {line.strip()}")
    return 0 if result.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
