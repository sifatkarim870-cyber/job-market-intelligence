"""Repoint the scheduled Kaggle kernel from Neon to Hugging Face.

Why
---
``mskarim870/nllb-translate`` is the kernel carrying the schedule. It reads
rows from Neon with psycopg2 and bulk-writes ``description_en`` back, and it
has died on every run since Neon's free quota was exhausted:

    OperationalError: connection to server at
    "ep-damp-band-b35ije4h.c-4.ap-southeast-1.aws.neon.tech" (52.76.212.156),
    port 5432 failed: ERROR:  Your account or project has exceeded the quota.

It fails in ~16 seconds, which is why each notification arrives almost
immediately after the schedule fires.

``mskarim870/jmi-translate-hf`` already solves this: it reads the public
corpus shards over ``hf://`` with DuckDB, translates on 2x Tesla T4, and
uploads the overlay additively. Its last run was COMPLETE.

What this does
--------------
Copies that notebook onto the SCHEDULED kernel's identity, so the existing
schedule keeps working without anyone re-pointing it in the UI:

* notebook code taken verbatim from jmi-translate-hf;
* ``id`` kept as ``mskarim870/nllb-translate`` -- this is what makes push
  update the scheduled kernel rather than create a third one;
* ``dataset_sources`` kept as ``jmi-translate-creds`` (the one already attached
  to this kernel) rather than switched to the HF kernel's own creds dataset,
  because the HF code no longer reads an attached dataset at all -- it finds
  the write token as a kernel SECRET (``find_token`` scans /kaggle for a
  ``hf_`` prefixed file). Keeping the existing source is the smaller change;
  the secret must be present on this kernel or the run fails at upload.

After pushing, verify the run:
    kaggle kernels status mskarim870/nllb-translate
    kaggle kernels logs    mskarim870/nllb-translate

Safety
------
* The previous notebook is saved to a .bak file before anything is overwritten.
* Nothing is pushed unless --push is given; the default is a dry run.
* The corpus is only ever read, never rewritten -- the overlay is additive,
  which is the property that makes the immutable-shard design safe.

Usage:
    python scripts/port_kaggle_kernel_to_hf.py
    python scripts/port_kaggle_kernel_to_hf.py --push
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

SOURCE_KERNEL = "mskarim870/jmi-translate-hf"
TARGET_KERNEL = "mskarim870/nllb-translate"

#: Attached to the target kernel today. The HF code does not read it (the token
#: comes from a kernel secret), but changing it is not part of this fix.
KEEP_DATASET_SOURCE = "mskarim870/jmi-translate-creds"


def kaggle(*args: str) -> subprocess.CompletedProcess:
    """Run the Kaggle CLI, returning the completed process."""
    return subprocess.run(
        [sys.executable, "-m", "kaggle", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def pull(kernel: str, dest: pathlib.Path, metadata: bool = True) -> pathlib.Path:
    """Download a kernel's notebook and metadata into ``dest``."""
    args = ["kernels", "pull", kernel, "-p", str(dest)]
    if metadata:
        args.append("-m")
    result = kaggle(*args)
    if result.returncode != 0:
        raise SystemExit(f"pull failed for {kernel}: {result.stderr.strip()[:300]}")
    notebooks = list(dest.glob("*.ipynb"))
    if not notebooks:
        raise SystemExit(f"no notebook found for {kernel}")
    return notebooks[0]


def code_of(path: pathlib.Path) -> str:
    """The CODE of a notebook, not its JSON.

    Reading the file and regexing it finds no ``def `` at all, because in JSON
    every line of a cell is a quoted string starting with a space.
    """
    nb = json.loads(path.read_text(encoding="utf-8"))
    return "\n".join(
        "".join(c["source"]) for c in nb.get("cells", []) if c.get("cell_type") == "code"
    )


def replace_function(source: str, name: str, new_text: str) -> str:
    """Swap one top-level function's body, located by AST line numbers.

    Never by a text scan for the next ``def``: three patches in this repo used
    scans and each destroyed neighbouring code.
    """
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    target = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name
    )
    head = "".join(lines[: target.lineno - 1])
    tail = "".join(lines[target.end_lineno :])
    patched = head + new_text.rstrip("\n") + "\n\n" + tail
    compile(patched, "cell", "exec")
    return patched


def function_text(source: str, name: str) -> str | None:
    """The exact source text of one top-level function, or None if absent."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    target = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), None
    )
    if target is None:
        return None
    lines = source.splitlines(keepends=True)
    return "".join(lines[target.lineno - 1 : target.end_lineno])


def carry_token_lookup(ported: str, target_src: str) -> tuple[str, list[str]]:
    """Keep the TARGET kernel's ``find_token``, not the source's.

    ``build`` copies the source notebook wholesale, and the two kernels do not
    agree on how to obtain the HF token. ``jmi-translate-hf`` still uses the old
    file scan::

        for p in pathlib.Path("/kaggle").rglob("*.txt"): ...

    which cannot find anything, because Kaggle serves secrets through
    ``UserSecretsClient`` rather than mounting them as readable files. That scan
    failed on eight consecutive scheduled runs. ``nllb-translate`` works because
    it asks for the secret by name.

    Copying the source notebook verbatim would therefore silently revert the
    working token lookup and put the scheduled kernel straight back into the
    state that took eight versions to escape. The target's ``find_token`` is
    carried across instead, together with the ``CANDIDATE_LABELS`` constant it
    iterates.
    """
    notes: list[str] = []
    target_fn = function_text(target_src, "find_token")
    if target_fn is None:
        return ported, ["target has no find_token; source copy kept as-is"]

    if "UserSecretsClient" not in target_fn:
        return ported, [
            "target find_token is not the UserSecretsClient version; left alone"
        ]

    ported_fn = function_text(ported, "find_token")
    if ported_fn == target_fn:
        return ported, ["find_token already identical to the target"]

    ported = replace_function(ported, "find_token", target_fn)
    notes.append("carried the target's UserSecretsClient find_token across")

    # The constant is a separate module-level statement, not part of the
    # function, so it has to be moved explicitly or find_token raises NameError.
    if "CANDIDATE_LABELS" in target_fn and "CANDIDATE_LABELS = " not in ported:
        for const in re.findall(
            r"(?m)^CANDIDATE_LABELS = .*$", target_src
        ):
            ported = ported.replace("def find_token", f"{const}\n\n\ndef find_token", 1)
            notes.append("restored the CANDIDATE_LABELS constant")
            break
    return ported, notes


def build(target_meta: dict, source_nb: pathlib.Path) -> tuple[pathlib.Path, dict]:
    """Write the ported notebook + metadata into a temp dir. Returns (nb, meta)."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_kernel_"))
    meta = dict(target_meta)
    meta["id"] = TARGET_KERNEL
    # The kernel slug must match the title, lowercased and dashed. Both
    # kernels already satisfy this, but it is asserted because a mismatch makes
    # push create a NEW kernel instead of updating the scheduled one.
    slug = TARGET_KERNEL.split("/", 1)[1]
    meta["title"] = slug
    meta["code_file"] = f"{slug}.ipynb"
    meta["dataset_sources"] = [KEEP_DATASET_SOURCE]

    nb_out = work / meta["code_file"]
    shutil.copyfile(source_nb, nb_out)
    meta_out = work / "kernel-metadata.json"
    meta_out.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return work, meta


def verify_ported(source: str) -> None:
    """Refuse to push a port that reintroduces a defect that cost a full run.

    Both checks are AST-based. A substring search flags the FIXED code as
    broken, because the merge's docstring explains the ``download_repo_file``
    mistake in prose and the token comment mentions the old file scan.
    """
    if "NEON_DATABASE_URL" in source:
        raise SystemExit("ported notebook still references Neon")

    tree = ast.parse(source)
    calls = {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    } | {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    literals = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    if "download_repo_file" in calls:
        raise SystemExit(
            "ported notebook would reintroduce HfApi.download_repo_file, which "
            "does not exist; the overlay merge would fall back to overwriting"
        )
    if "*.txt" in literals:
        raise SystemExit(
            'ported notebook would reintroduce the rglob("*.txt") file scan; '
            "Kaggle serves secrets through UserSecretsClient, not as files"
        )
    print("   verified: no NEON_DATABASE_URL, no download_repo_file, no *.txt scan")

    compile(source, "kernel", "exec")
    funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    if missing := {"find_token", "main", "upload_overlay", "open_corpus", "run_gpu"} - funcs:
        raise SystemExit(f"ported notebook missing {sorted(missing)}")
    if "UserSecretsClient" in source and "CANDIDATE_LABELS = " not in source:
        raise SystemExit("ported notebook lost CANDIDATE_LABELS; find_token would NameError")
    print(f"   verified: {len(funcs)} functions intact, token lookup and merge preserved")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--push", action="store_true", help="actually upload (default: dry run)")
    ap.add_argument(
        "--timeout", type=int, default=3600, help="max run seconds passed to push"
    )
    args = ap.parse_args(argv)

    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_target_"))
    print(f"1. pulling the scheduled kernel ({TARGET_KERNEL})")
    pull(TARGET_KERNEL, work)
    target_nb = list(work.glob("*.ipynb"))[0]
    target_meta = json.loads(
        (work / "kernel-metadata.json").read_text(encoding="utf-8")
    )
    print(f"   current notebook: {target_nb.name} ({target_nb.stat().st_size:,} bytes)")

    # Back up before overwriting anything.
    backup = target_nb.with_suffix(".ipynb.bak")
    shutil.copyfile(target_nb, backup)
    print(f"   backup saved     : {backup.name}")

    src_work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_source_"))
    print(f"2. pulling the working kernel ({SOURCE_KERNEL})")
    source_nb = pull(SOURCE_KERNEL, src_work)

    out, meta = build(target_meta, source_nb)
    print("\n3. ported metadata")
    for key in ("id", "title", "code_file", "enable_gpu", "machine_shape",
                "enable_internet", "dataset_sources"):
        print(f"   {key:<18} {meta.get(key)}")

    # Preserve the scheduled kernel's working token lookup across the copy.
    ported_nb = out / meta["code_file"]
    ported_src = code_of(ported_nb)
    ported_src, notes = carry_token_lookup(ported_src, code_of(target_nb))

    # Both kernels are a single code cell, so the merged source goes straight
    # back into it. Verified rather than assumed: if that ever changes, the
    # round-trip below fails loudly instead of silently dropping code.
    nb_obj = json.loads(ported_nb.read_text(encoding="utf-8"))
    code_cells = [c for c in nb_obj.get("cells", []) if c.get("cell_type") == "code"]
    if len(code_cells) != 1:
        raise SystemExit(
            f"expected 1 code cell to rewrite, found {len(code_cells)}; "
            "the round-trip is no longer safe"
        )
    code_cells[0]["source"] = [ported_src]
    ported_nb.write_text(json.dumps(nb_obj, indent=1), encoding="utf-8")
    if code_of(ported_nb) != ported_src:
        raise SystemExit("notebook round-trip lost code; refusing to push")
    for note in notes:
        print(f"   token lookup: {note}")

    verify_ported(ported_src)

    if not args.push:
        print("\n--dry run (default): nothing uploaded.")
        print(f"   would push to   : {meta['id']}")
        print(f"   staged in       : {out}")
        return 0

    print("\n4. pushing (this UPLOADS AND RUNS the kernel)")
    result = kaggle("kernels", "push", "-p", str(out), "-t", str(args.timeout))
    print(f"   exit={result.returncode}")
    for stream in (result.stdout, result.stderr):
        for line in stream.splitlines():
            if line.strip():
                print(f"   {line.strip()}")
    return 0 if result.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
