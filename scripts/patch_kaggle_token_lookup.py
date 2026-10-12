"""Make the kernel's HF-token lookup independent of the secret's file extension.

Why
---
The kernel finds its write token like this::

    def find_token():
        for p in pathlib.Path("/kaggle").rglob("*.txt"):
            t = p.read_text().strip()
            if t.startswith("hf_") and len(t) > 20:
                return t
        raise SystemExit("no HF token found -- attach it as a kernel secret")

Kaggle mounts a secret at ``/kaggle/secrets/<label>``. A secret labelled
``hf_token`` therefore lands at ``/kaggle/secrets/hf_token`` -- with NO ``.txt``
extension -- and ``rglob("*.txt")`` cannot match it. The secret has to be
labelled ``hf_token.txt`` or the kernel cannot see it at all.

That is a silent, configuration-only failure: the kernel runs, does all the
work, and then dies on the last line with a message about attaching a secret
that is already attached and ticked.

This rewrites the lookup to scan every file under /kaggle and select by
CONTENT (a string starting with "hf_"), never by name. That is both simpler and
strictly more permissive: it works whatever the secret is called.

Safety
------
* Dry run by default; ``--push`` uploads AND runs the kernel.
* The current notebook is backed up first.
* Only ``find_token`` is changed; the rest of the notebook is untouched.

Usage:
    python scripts/patch_kaggle_token_lookup.py
    python scripts/patch_kaggle_token_lookup.py --push
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

KERNEL = "mskarim870/nllb-translate"

#: The exact function being replaced, as it appears in the notebook source.
OLD = '''def find_token():
    for p in pathlib.Path("/kaggle").rglob("*.txt"):
        try:
            t = p.read_text().strip()
        except Exception:
            continue
        if t.startswith("hf_") and len(t) > 20:
            return t
    raise SystemExit("no HF token found -- attach it as a kernel secret")'''

NEW = '''def find_token():
    # Scan by CONTENT, never by file extension. Kaggle mounts a secret at
    # /kaggle/secrets/<label>, so a secret labelled "hf_token" has NO .txt
    # suffix and an rglob("*.txt") cannot match it -- the kernel then runs to
    # completion and fails on the last line claiming no secret is attached.
    # Selecting on content makes the label irrelevant.
    for p in pathlib.Path("/kaggle").rglob("*"):
        if not p.is_file():
            continue
        try:
            t = p.read_text(errors="ignore").strip()
        except Exception:
            continue
        if t.startswith("hf_") and len(t) > 20:
            return t
    raise SystemExit(
        "no HF token found. Attach it as a Kaggle secret (Add-ons -> Secrets) "
        "and tick the read checkbox."
    )'''


def kaggle(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "kaggle", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def patch_notebook(nb_path: pathlib.Path) -> bool:
    """Replace find_token in the notebook. Returns True if it changed."""
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    changed = False

    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell["source"])
        if "def find_token()" not in source:
            continue
        # The notebook source carries escaped newlines inside a single string
        # element, so the match is done on the joined source and written back
        # as one entry -- the shape Kaggle and papermill both read correctly.
        if OLD not in source:
            raise SystemExit(
                "find_token was found but does not match the expected text.\n"
                "The kernel source has changed; re-read it before patching."
            )
        cell["source"] = [source.replace(OLD, NEW)]
        changed = True

    if changed:
        nb_path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--push", action="store_true", help="upload and run (default: dry run)")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args(argv)

    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_nlpull_"))
    result = kaggle("kernels", "pull", KERNEL, "-p", str(work), "-m")
    if result.returncode != 0:
        raise SystemExit(f"pull failed: {result.stderr.strip()[:300]}")

    nb_path = list(work.glob("*.ipynb"))[0]
    backup = nb_path.with_suffix(".ipynb.bak")
    shutil.copyfile(nb_path, backup)
    print(f"pulled {nb_path.name} ({nb_path.stat().st_size:,} bytes); backup saved")

    changed = patch_notebook(nb_path)
    if not changed:
        raise SystemExit("no find_token() found -- nothing to patch")
    print(f"patched find_token(); notebook now {nb_path.stat().st_size:,} bytes")

    if not args.push:
        print("\n--dry run (default): nothing uploaded.")
        print(f"   staged in {work}")
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
