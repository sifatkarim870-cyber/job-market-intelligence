"""Attach the Hugging Face write token to a Kaggle kernel as a secret.

Why
---
The ported translation kernel finds its write token by scanning ``/kaggle`` for
a ``*.txt`` file whose content starts with ``hf_``::

    def find_token():
        for p in pathlib.Path("/kaggle").rglob("*.txt"):
            ...
        raise SystemExit("no HF token found -- attach it as a kernel secret")

That works on ``jmi-translate-hf`` because the token is attached there as a
Kaggle secret. The kernel carrying the schedule did not have it, so the first
run translated successfully and then died on the final upload with::

    SystemExit: no HF token found -- attach it as a kernel secret

Kernels do not expose their attached secrets through the API, so there is no
way to copy it between kernels programmatically -- it has to be attached in the
Kaggle UI. This script verifies the situation and prints the exact steps, and
can verify the fix afterwards.

It NEVER prints the token.

Usage:
    python scripts/check_kaggle_kernel_token.py --kernel mskarim870/nllb-translate
    python scripts/check_kaggle_kernel_token.py --kernel mskarim870/nllb-translate --wait
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

TOKEN_FILE = pathlib.Path(
    r"D:\Research_Project\JobMarketAnalysisPlatform\DataBase\Hugging_Face_token.txt"
)

STEPS = """\
Kaggle secrets cannot be read or written through the API -- only the UI can
attach one -- so this has to be done by hand, once:

  1. Open   https://www.kaggle.com/code/{kernel}
  2. Click  "Add-ons" in the right-hand sidebar, then "Secrets"
  3. Add a secret:
        Label:  hf_token
        Value:  <the token from Hugging Face, Settings -> Access Tokens>
  4. IMPORTANT: tick the check-box next to it so the kernel can READ it
  5. Save, then re-run the notebook (or wait for the next scheduled run)

The label must be one the kernel globs for. find_token() scans every *.txt
under /kaggle, so "hf_token" works; a label ending in something other than
.txt may not be picked up.

Verify afterwards with:
  kaggle kernels logs {kernel} | grep -i "hf token"
A healthy run ends with the overlay upload, not a SystemExit."""


def _token_available() -> bool:
    return TOKEN_FILE.exists() and TOKEN_FILE.read_text(encoding="utf-8").strip().startswith(
        "hf_"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kernel", default="mskarim870/nllb-translate")
    ap.add_argument(
        "--wait",
        action="store_true",
        help="poll the latest run and report whether it still fails on the token",
    )
    args = ap.parse_args(argv)

    if not _token_available():
        print(
            "WARNING: no usable HF token found at "
            f"{TOKEN_FILE}\n"
            "         You will need one to paste into the Kaggle secret."
        )
    else:
        print("HF token file found locally (value never printed).")

    print(f"\nkernel: {args.kernel}")

    if args.wait:
        print("\npolling the most recent run...\n")
        for _ in range(20):
            result = subprocess.run(
                [sys.executable, "-m", "kaggle", "kernels", "logs", args.kernel],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            logs = result.stdout + result.stderr
            if "no HF token found" in logs:
                print("  still failing: the secret is not attached (or not ticked).")
                return 1
            if "uploaded" in logs.lower() or "overlay" in logs.lower():
                print("  looks healthy: the overlay upload path was reached.")
                return 0
            if "exceeded the quota" in logs:
                print("  still failing on NEON -- the notebook was not repointed.")
                return 1
            time.sleep(30)
        print("  no conclusive signal in the latest logs yet.")

    print("\n" + STEPS.format(kernel=args.kernel))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
