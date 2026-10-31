"""Re-queue the scheduled translation kernel when Kaggle gives it a CPU slot.

Why this exists
---------------
The daily Kaggle schedule for ``mskarim870/jmi-translate-hf`` fires at
09:03 UTC, and every scheduled firing observed (2026-10-24, -28, -29, -30,
-31) was allocated a CPU-only slot -- ``{"torch": "2.11.0+cpu", "gpus": 0}`` --
where the kernel's fail-fast guard aborts in ~10 seconds with::

    SystemExit: no GPU allocated: Kaggle gave this session a CPU-only torch
    build. Re-run when a GPU slot is available.

The kernel code and its metadata are correct: ``enable_gpu: true``,
``machine_shape: NvidiaTeslaT4``, the CUDA BYOD image. The difference is in how
the two triggers enter Kaggle's queue:

* a manual ``kaggle kernels push`` **waits for a GPU** -- 3 for 3 successes
  (v51, v53, v56, all ``gpus: 2``);
* a UI-scheduled session does **not wait** -- when no T4 is free at 09:03 UTC
  it starts on CPU instead of queueing, and at peak free-tier demand a GPU is
  apparently never free at that hour.

Kaggle's API exposes no schedule fields to fix, the schedule UI has no
accelerator setting, and -- critically -- Kaggle returns HTTP 403 for its
``/api/v1/kernels/status`` endpoint from GitHub Actions' datacenter IP range
(verified: the watchdog's first scheduled run on 2026-10-31 got 403 on all
three status checks). So this watchdog does **not** call Kaggle at all. It uses
the Hugging Face translations dataset as the system of record: if today's
scheduled run succeeded, the overlay file was re-published after the window
opened (a healthy GPU run publishes within ~10 minutes). If the overlay was
*not* updated today on/after the scheduled window, the scheduled run died and
the watchdog re-pushes the current notebook verbatim -- a push is also a run,
and a push queues for a GPU.

Failure semantics
-----------------
The script exits 1 whenever today's overlay is stale (the scheduled run failed
today), *including* after a successful re-push. A red X is the notification:
"the scheduled run failed today." The status detail is printed so the Actions
annotation says why. On a fresh overlay it exits 0 and does nothing.

If Hugging Face is unreachable, the script exits 1 **without** pushing -- a
stale overlay with an unreachable signal must not trigger a blind double-run.

The kaggle CLI is invoked as a subprocess (``{sys.executable} -m kaggle``),
the same pattern as ``fix_overlay_overwrite.py``: this file imports nothing
outside the standard library, because ``test_declared_dependencies.py`` audits
every import in ``scripts/`` against pyproject.toml and ``kaggle`` is
deliberately not a project dependency. Run it with the CLI provided at runtime::

    KAGGLE_USERNAME=... KAGGLE_KEY=... \
        uv run --with kaggle python scripts/kaggle_watchdog.py

Credentials come from the ``KAGGLE_USERNAME``/``KAGGLE_KEY`` environment
variables (what CI uses) and fall back to ``~/.kaggle/kaggle.json`` for local
runs. HF is read anonymously (the dataset is public), so no HF token is needed
for the staleness check.

Usage:
    python scripts/kaggle_watchdog.py
    python scripts/kaggle_watchdog.py --dry-run
    python scripts/kaggle_watchdog.py --kernel mskarim870/jmi-translate-hf
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

KERNEL = "mskarim870/jmi-translate-hf"
HF_DATASET = "Shifat2110724169/job-market-intel-translations"
HF_INFO_URL = f"https://huggingface.co/api/datasets/{HF_DATASET}"

#: Kaggle's daily schedule fires the kernel at this UTC time.
SCHEDULE_UTC = _dt.time(9, 3)

#: The watchdog runs this many minutes after the window, giving a healthy GPU
#: run (~10 min incl. smoke test and translation) time to publish.
WATCHDOG_OFFSET_MIN = 20

#: Statuses Kaggle's API returns for a dead run (kept for documentation; the
#  status check itself is unavailable from CI due to Kaggle's 403, so the
#  decision is made from HF staleness instead).
DEAD_STATUSES = frozenset({"error", "cancelacknowledged"})

#: The pulled metadata must carry exactly this GPU configuration. Refusing to
#  push a degraded pull is the watchdog's one remediation attempt not spending
#  itself re-creating the CPU failure it exists to fix.
EXPECTED_META = {
    "enable_gpu": True,
    "machine_shape": "NvidiaTeslaT4",
}


def kaggle_cli(*args: str) -> subprocess.CompletedProcess:
    """Run the kaggle CLI, returning the completed process."""
    return subprocess.run(
        [sys.executable, "-m", "kaggle", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def credentials() -> tuple[str, str]:
    """KAGGLE_USERNAME/KAGGLE_KEY from the environment, else ~/.kaggle/kaggle.json."""
    user, key = os.environ.get("KAGGLE_USERNAME"), os.environ.get("KAGGLE_KEY")
    if user and key:
        return user, key
    token_file = pathlib.Path.home() / ".kaggle" / "kaggle.json"
    if token_file.is_file():
        token = json.loads(token_file.read_text(encoding="utf-8"))
        return token["username"], token["key"]
    raise SystemExit(
        "no Kaggle credentials: set KAGGLE_USERNAME and KAGGLE_KEY (or place "
        "kaggle.json in ~/.kaggle)"
    )


def today_utc() -> _dt.date:
    return _dt.datetime.now(_dt.UTC).date()


def hf_last_modified(attempts: int = 3) -> _dt.datetime | None:
    """Return the overlay dataset's last-modified instant, or None if unreachable.

    The dataset is public, so this works with no token. Retries transient
    failures; a real HF outage fails loudly on the third attempt and the caller
    refuses to push blindly.
    """
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(HF_INFO_URL, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            raw = data.get("lastModified")
            if not raw:
                return None
            return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception as exc:  # noqa: BLE001 - any transport error is retryable
            last_error = exc
            if attempt < attempts:
                time.sleep(10 * attempt)
    print(f"hf dataset unreachable after {attempts} attempts: {last_error}")
    return None


def overlay_is_fresh(last_modified: _dt.datetime | None) -> bool:
    """True if the overlay was (re)published today on/after the schedule window."""
    if last_modified is None:
        return False
    today = today_utc()
    if last_modified.date() != today:
        return False
    window_open = _dt.datetime.combine(today, SCHEDULE_UTC, tzinfo=_dt.UTC)
    return last_modified >= window_open


def decide(fresh: bool) -> str:
    """Map overlay staleness to the watchdog's action: 'repush' or 'noop'."""
    return "noop" if fresh else "repush"


def verify_pulled(meta: dict, notebook_source: str) -> None:
    """Refuse to push unless the pull still carries the working configuration."""
    for field, expected in EXPECTED_META.items():
        if meta.get(field) != expected:
            raise SystemExit(
                f"pulled metadata has {field}={meta.get(field)!r}, expected "
                f"{expected!r} -- refusing to push a pull that lost the GPU "
                "configuration"
            )
    if "kaggle-private-byod" not in (meta.get("docker_image") or ""):
        raise SystemExit(
            f"pulled metadata pins docker_image={meta.get('docker_image')!r}, "
            "not the CUDA BYOD image -- refusing to push"
        )
    if "mskarim870/jmi-translate-creds" not in (meta.get("dataset_sources") or []):
        raise SystemExit(
            f"pulled metadata lost the creds dataset ({meta.get('dataset_sources')!r}) "
            "-- the kernel would fail on find_token; refusing to push"
        )
    if "NEON_DATABASE_URL" in notebook_source:
        raise SystemExit("pulled notebook still references Neon -- refusing to push")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kernel", default=KERNEL)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="report the staleness decision, but never push",
    )
    args = ap.parse_args(argv)

    user, key = credentials()
    last_modified = hf_last_modified()
    fresh = overlay_is_fresh(last_modified)
    action = decide(fresh)

    print(f"kernel : {args.kernel}")
    print(f"hf overlay last_modified: {last_modified.isoformat() if last_modified else 'unreachable'}")
    print(f"schedule window opened today at {SCHEDULE_UTC.isoformat()} UTC")
    print(f"overlay fresh: {fresh}")
    print(f"action : {action}")

    if action == "noop":
        print("nothing to do: today's scheduled run already published translations")
        return 0

    if last_modified is None:
        print("refusing to re-push: hf unreachable, cannot confirm staleness")
        return 1

    if args.dry_run:
        print("--dry-run: would re-push the current notebook to re-queue a GPU run")
        return 1

    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_watchdog_"))
    result = kaggle_cli("kernels", "pull", args.kernel, "-p", str(work), "-m")
    if result.returncode != 0:
        print(f"pull failed: {(result.stderr or result.stdout).strip()[:300]}")
        return 1

    nb_path = next(work.glob("*.ipynb"), None)
    meta_path = work / "kernel-metadata.json"
    if nb_path is None or not meta_path.is_file():
        print(f"pull produced no notebook/metadata pair in {work}")
        return 1
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    source = "".join(
        "".join(cell.get("source", []))
        for cell in nb.get("cells", [])
        if cell.get("cell_type") == "code"
    )
    try:
        verify_pulled(meta, source)
    except SystemExit as exc:
        print(f"verification refused the push: {exc}")
        return 1

    print("pushing the current notebook (uploads AND runs; a push queues for GPU)")
    result = kaggle_cli("kernels", "push", "-p", str(work))
    for stream in (result.stdout, result.stderr):
        for line in stream.splitlines():
            if line.strip():
                print(f"   {line.strip()}")
    if result.returncode != 0:
        print("re-push FAILED -- the kernel stays dead until the next watchdog run")
        return 1

    # Exit 1 on purpose: the scheduled run still failed today, and the red X is
    # the notification. The re-push is remediation, not a clean bill of health.
    print("re-push accepted; the run is queued for a GPU slot")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
