"""Define CANDIDATE_LABELS inside the Kaggle kernel notebook.

The bug
-------
``find_token`` was rewritten to try several secret labels in order, but the
tuple it iterates was never defined in the notebook -- the constant existed
only in the patching script that injected the function. Running the kernel
standalone therefore produced::

    [153s] checkpoint upload failed: name 'CANDIDATE_LABELS' is not defined
    [367s] FINAL UPLOAD FAILED: name 'CANDIDATE_LABELS' is not defined

Seven minutes of work, then a NameError on the final line. A module-level
constant used by a function has to live in the module; the script that writes
the module is not part of the kernel's runtime.

What this does NOT change
------------------------
The HTTP 429 seen in the same run is already handled correctly by the kernel.
The corpus walk is wrapped as::

    try:
        batch = fetch_pending(con, offset)
    except Exception as exc:
        state["errors"].append(f"fetch@{offset}: {exc}")
        log(f"fetch failed at {offset}: {exc}")
        break

so a rate limit stops the walk and the run still uploads whatever it collected.
That is the right behaviour -- rows already gathered are valid, and the next
run re-fetches the rest -- so no change is made to it. Earlier drafts of this
script tried to add a second layer of 429 handling around a loop that did not
exist; the loop is a ``while True:``, not a ``for offset in range(...)``.

Safety
------
* Dry run by default; ``--push`` uploads AND runs.
* The notebook is backed up first.
* Refuses to push if any top-level function went missing, or if the result
  does not compile.

Usage:
    python scripts/patch_kaggle_runtime_fixes.py
    python scripts/patch_kaggle_runtime_fixes.py --push
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

KERNEL = "mskarim870/nllb-translate"

CONSTANT = '''#: Secret labels tried in order by find_token. Only one is correct on a given
#: kernel and the label was chosen by hand, so all plausible spellings are
#: attempted. Defined HERE rather than in the script that injects find_token,
#: because the kernel runs standalone: referencing this name without defining
#: it cost a full seven-minute run that ended with
#: "name 'CANDIDATE_LABELS' is not defined" on its final line.
CANDIDATE_LABELS = ("hf_token.txt", "hf_token", "HUGGING_FACE_TOKEN", "huggingface_token")

'''

ANCHOR = "def find_token():"


def kaggle(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "kaggle", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def patch(nb_path: pathlib.Path) -> bool:
    """Insert the constant immediately before find_token, if it is missing."""
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    changed = False

    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell["source"])
        if ANCHOR not in source or "CANDIDATE_LABELS = " in source:
            continue
        idx = source.index(ANCHOR)
        cell["source"] = [source[:idx] + CONSTANT + source[idx:]]
        changed = True

    if changed:
        nb_path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    return changed


def sanity(src: str) -> None:
    """Refuse to push a notebook that lost a function or stopped compiling."""
    defined = set(re.findall(r"(?m)^(?:def|class)\s+(\w+)", src))
    required = {"find_token", "main", "upload_overlay", "open_corpus", "run_gpu"}
    missing = required - defined
    if missing:
        raise SystemExit(f"notebook missing {sorted(missing)}; refusing to push")
    try:
        compile(src, "kernel", "exec")
    except SyntaxError as exc:
        raise SystemExit(f"patched notebook does not compile: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args(argv)

    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_fix_"))
    result = kaggle("kernels", "pull", KERNEL, "-p", str(work), "-m")
    if result.returncode != 0:
        raise SystemExit(f"pull failed: {result.stderr.strip()[:300]}")

    nb = list(work.glob("*.ipynb"))[0]
    shutil.copyfile(nb, nb.with_suffix(".ipynb.bak"))
    print(f"pulled {nb.name} ({nb.stat().st_size:,} bytes)")

    if not patch(nb):
        print("CANDIDATE_LABELS already defined; nothing to do")
        return 0
    print(f"injected the constant; now {nb.stat().st_size:,} bytes")

    # Sanity runs on the CODE, not the notebook JSON. Reading the file and
    # regexing it finds no `def ` at all, because in JSON every line of the
    # cell source is a quoted string that starts with a space -- so this
    # reported every function as missing and blocked a correct patch.
    code = "\n".join(
        "".join(c["source"])
        for c in json.loads(nb.read_text(encoding="utf-8"))["cells"]
        if c["cell_type"] == "code"
    )
    assert "NEON_DATABASE_URL" not in code
    sanity(code)
    print("sanity: functions intact, notebook compiles, constant present")
    assert "CANDIDATE_LABELS = " in code

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
