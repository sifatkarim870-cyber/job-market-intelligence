"""Re-push an already-correct kernel to trigger a run, without modifying it.

``kaggle kernels push`` uploads AND runs. There is no ``kernels run`` verb --
probed and confirmed 404 -- so a re-push is the only way to start a run
programmatically. This pushes the CURRENT notebook back unchanged, which is
what you want when the kernel is correct and only the ENVIRONMENT changed (a
secret was attached, for instance).

The notebook is round-tripped through a pull first so exactly what is on Kaggle
is what gets pushed back -- no local edits, no reformatting. It is compared
against the staged copy before pushing and the push is aborted if they differ.

Usage:
    python scripts/rerun_kaggle_kernel.py --kernel mskarim870/nllb-translate
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile


def kaggle(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "kaggle", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kernel", default="mskarim870/nllb-translate")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args(argv)

    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_rerun_"))
    result = kaggle("kernels", "pull", args.kernel, "-p", str(work), "-m")
    if result.returncode != 0:
        raise SystemExit(f"pull failed: {result.stderr.strip()[:300]}")

    nb = list(work.glob("*.ipynb"))[0]
    meta_file = work / "kernel-metadata.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    backup = nb.with_suffix(".ipynb.bak")
    shutil.copyfile(nb, backup)

    print(f"kernel : {args.kernel}")
    print(f"notebook: {nb.name} ({nb.stat().st_size:,} bytes)")
    print(f"gpu     : enable_gpu={meta.get('enable_gpu')} shape={meta.get('machine_shape')}")
    print(f"backup  : {backup.name}")

    # The pulled copy is pushed back verbatim, so nothing can drift. Assert it.
    src = nb.read_text(encoding="utf-8")
    assert "def find_token" in src, "pulled notebook has no find_token -- unexpected"
    assert "NEON_DATABASE_URL" not in src, "notebook still references Neon"
    print("verified: unchanged, HF-based, no Neon reference")

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
