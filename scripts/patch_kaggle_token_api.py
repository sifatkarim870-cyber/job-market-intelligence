"""Make the kernel read its HF token through Kaggle's documented API.

Why the file scan was wrong
---------------------------
The kernel looked for its token by scanning /kaggle for a *.txt file whose
content starts with "hf_". That assumes Kaggle mounts an attached secret as a
readable FILE. It does not: secrets are served through ``UserSecretsClient``,
which is what Kaggle's own "Code Snippet" panel generates for an attached
secret::

    from kaggle_secrets import UserSecretsClient
    user_secrets = UserSecretsClient()
    secret_value_0 = user_secrets.get_secret("hf_token.txt")

With the secret correctly attached AND ticked in the UI, the file scan still
found nothing, and every run ended with a message claiming no secret was
attached -- which was actively misleading, because one was.

What this does
--------------
Replaces ``find_token`` with a version that asks ``UserSecretsClient`` for each
known label spelling, and only then falls back to scanning /kaggle. The
fallback costs nothing and covers a filesystem-mounted secret if Kaggle ever
restores that behaviour.

Candidate labels are tried in order because the label is user-chosen: the
kernel is named for this project and the secret was created by hand, so the
extension may or may not be present.

Usage:
    python scripts/patch_kaggle_token_api.py
    python scripts/patch_kaggle_token_api.py --push
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

#: Labels tried against UserSecretsClient, in order. Only one is correct on a
#: given kernel and the label was chosen by hand, so all plausible spellings
#: are attempted before giving up.
CANDIDATE_LABELS = (
    "hf_token.txt",
    "hf_token",
    "HUGGING_FACE_TOKEN",
    "huggingface_token",
)

OLD_HEAD = "def find_token():"

NEW = """def find_token():
    # Ask Kaggle for the secret by NAME first. Secrets are served through
    # UserSecretsClient, NOT mounted as readable files under /kaggle, so the
    # old rglob("*.txt") scan found nothing even with the secret correctly
    # attached and ticked -- and its error message claimed otherwise.
    try:
        from kaggle_secrets import UserSecretsClient

        client = UserSecretsClient()
        for label in CANDIDATE_LABELS:
            try:
                token = (client.get_secret(label) or "").strip()
            except Exception:
                continue
            if token.startswith("hf_") and len(token) > 20:
                print(f"[find_token] using Kaggle secret label={label!r}")
                return token
    except ImportError:
        pass

    # Fallback: a secret mounted as a file (older Kaggle behaviour). Scans by
    # content, never by extension, so the label's suffix is irrelevant.
    for p in pathlib.Path("/kaggle").rglob("*"):
        if not p.is_file():
            continue
        try:
            t = p.read_text(errors="ignore").strip()
        except Exception:
            continue
        if t.startswith("hf_") and len(t) > 20:
            print(f"[find_token] using mounted file {p}")
            return t

    raise SystemExit(
        "no HF token found. Tried UserSecretsClient labels "
        f"{CANDIDATE_LABELS} and a /kaggle file scan. Attach the token as a "
        "Kaggle secret and tick its read checkbox."
    )"""


def kaggle(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "kaggle", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def patch(nb_path: pathlib.Path) -> bool:
    """Replace find_token's body, and nothing else.

    A first attempt located the function's end by scanning forward for the next
    line starting with ``def``. That was wrong: the scan also stopped on any
    line beginning with ``# ``, ran past the real boundary, and deleted
    ``main()`` outright -- the pushed kernel then died with

        NameError: name 'main' is not defined

    The boundary is now anchored on COLUMN 0: the next ``def `` or ``class ``
    starting at the left margin. A nested ``def`` is always indented, so this
    cannot stop early, and only find_token is replaced.
    """
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    changed = False

    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell["source"])
        if OLD_HEAD not in source:
            continue
        if "UserSecretsClient" in source:
            print("   find_token already uses UserSecretsClient; nothing to do")
            return False

        start = source.index(OLD_HEAD)
        tail = source[start + len(OLD_HEAD) :]
        boundary = re.search(r"(?m)^(?:def |class )", tail)
        end = start + len(OLD_HEAD) + boundary.start() if boundary else len(source)

        cell["source"] = [source[:start] + NEW + "\n\n" + source[end:]]
        changed = True

    if changed:
        nb_path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    return changed


def sanity(src: str) -> None:
    """Refuse to push a notebook that lost a top-level function."""
    defined = set(re.findall(r"(?m)^(?:def|class)\s+(\w+)", src))
    required = {"find_token", "main", "upload_overlay", "open_corpus", "run_gpu"}
    missing = required - defined
    if missing:
        raise SystemExit(
            f"patched notebook is missing {sorted(missing)}; refusing to push. "
            "The replacement must not delete surrounding code."
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args(argv)

    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_tok_"))
    result = kaggle("kernels", "pull", KERNEL, "-p", str(work), "-m")
    if result.returncode != 0:
        raise SystemExit(f"pull failed: {result.stderr.strip()[:300]}")

    nb = list(work.glob("*.ipynb"))[0]
    shutil.copyfile(nb, nb.with_suffix(".ipynb.bak"))
    print(f"pulled {nb.name} ({nb.stat().st_size:,} bytes)")

    if not patch(nb):
        raise SystemExit("nothing patched")
    print(f"patched find_token -> UserSecretsClient; now {nb.stat().st_size:,} bytes")

    src = nb.read_text(encoding="utf-8")
    assert "UserSecretsClient" in src
    assert "NEON_DATABASE_URL" not in src
    sanity(src)
    print("sanity: all top-level functions intact")

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
