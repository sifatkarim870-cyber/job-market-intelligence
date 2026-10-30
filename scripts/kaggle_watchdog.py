"""Re-queue the scheduled translation kernel when Kaggle gives it a CPU slot.

Why this exists
---------------
The daily Kaggle schedule for ``mskarim870/jmi-translate-hf`` fires at
09:03 UTC, and every scheduled firing observed so far (2026-10-24, -28, -29,
-30) was allocated a CPU-only slot -- ``{"torch": "2.11.0+cpu", "gpus": 0}`` --
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

Kaggle's API exposes no schedule fields to fix, and the schedule UI itself has
no accelerator setting (checked in the editor: only the notebook's side panel
does, and the schedule ignores it). So the fix is not a setting -- it is this
watchdog: after the scheduled window, check ``kernels status``; if the run
errored, re-push the *current* notebook verbatim (a push is also a run, and a
push queues for GPU). The re-push is a pull->verify->push roundtrip so exactly
what Kaggle serves is what goes back; the metadata sanity checks refuse to
push a pull that lost the GPU config or the creds dataset.

Failure semantics
-----------------
The script exits 1 whenever the observed status is ``error`` (or
``cancelacknowledged``), *including* after a successful re-push. A red X is the
notification: the day's scheduled run failed, even if the watchdog rescued the
translations. The status message (e.g. the SystemExit text) is printed so the
Actions annotation says why. On ``running``/``queued``/``complete`` it exits 0
and does nothing -- a run in flight must not be double-started.

The kaggle CLI is invoked as a subprocess (``{sys.executable} -m kaggle``), the
same pattern as ``fix_overlay_overwrite.py``: this file imports nothing outside
the standard library, because ``test_declared_dependencies.py`` audits every
import in ``scripts/`` against pyproject.toml and ``kaggle`` is deliberately
not a project dependency. Run it with the CLI provided at runtime::

    KAGGLE_USERNAME=... KAGGLE_KEY=... \
        uv run --with kaggle python scripts/kaggle_watchdog.py

Credentials come from the ``KAGGLE_USERNAME``/``KAGGLE_KEY`` environment
variables (what CI uses) and fall back to ``~/.kaggle/kaggle.json`` for local
runs.

Usage:
    python scripts/kaggle_watchdog.py
    python scripts/kaggle_watchdog.py --dry-run
    python scripts/kaggle_watchdog.py --kernel mskarim870/jmi-translate-hf
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.request

KERNEL = "mskarim870/jmi-translate-hf"
STATUS_URL = "https://www.kaggle.com/api/v1/kernels/status?userName={user}&kernelSlug={slug}"

#: Statuses that mean the day's scheduled run is dead and a re-push is the fix.
#: ``cancelacknowledged`` is Kaggle's way of reporting a cancelled run.
DEAD_STATUSES = frozenset({"error", "cancelacknowledged"})

#: The pulled metadata must carry exactly this GPU configuration. If a future
#: Kaggle API change drops or renames these fields, refusing to push is the
#: right reaction: a push with ``enable_gpu`` missing could silently start a
#: CPU run -- the exact failure this watchdog exists to fix.
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


def fetch_status(user: str, key: str, attempts: int = 3) -> dict:
    """GET the kernel's run status, retrying transient network failures.

    A single flaky request must not flip the decision to re-push or, worse,
    mask a dead run as healthy. Three attempts with a short backoff covers a
    blip; a real outage fails loudly on the third.
    """
    auth = base64.b64encode(f"{user}:{key}".encode()).decode()
    url = STATUS_URL.format(user=user.split("/")[0], slug=KERNEL.split("/")[-1])
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - any transport error is retryable
            last_error = exc
            if attempt < attempts:
                time.sleep(10 * attempt)
    raise SystemExit(f"kernels status unreachable after {attempts} attempts: {last_error}")


def decide(status: str) -> str:
    """Map a kernel status to the watchdog's action: 'repush' or 'noop'."""
    return "repush" if status.strip().lower() in DEAD_STATUSES else "noop"


def verify_pulled(meta: dict, notebook_source: str) -> None:
    """Refuse to push unless the pull still carries the working configuration.

    Checked before the push, never after: pushing a degraded pull would
    re-create the CPU failure this watchdog is fixing, and the day's only
    remediation attempt would be spent making things worse.
    """
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


def _notebook_source(notebook: dict) -> str:
    """Concatenate the source of every code cell in a pulled notebook."""
    return "".join(
        "".join(cell.get("source", []))
        for cell in notebook.get("cells", [])
        if cell.get("cell_type") == "code"
    )


def repush(kernel: str) -> int:
    """Pull the current notebook, verify it, and push it back to queue a GPU run.

    Always returns 1 on purpose: the day's scheduled run still failed, and the
    red X is the notification. A successful re-push is remediation, not a clean
    bill of health.
    """
    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_watchdog_"))
    result = kaggle_cli("kernels", "pull", kernel, "-p", str(work), "-m")
    if result.returncode != 0:
        print(f"pull failed: {(result.stderr or result.stdout).strip()[:300]}")
        return 1

    nb_path = next(work.glob("*.ipynb"), None)
    meta_path = work / "kernel-metadata.json"
    if nb_path is None or not meta_path.is_file():
        print(f"pull produced no notebook/metadata pair in {work}")
        return 1
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    source = _notebook_source(json.loads(nb_path.read_text(encoding="utf-8")))
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

    print("re-push accepted; the run is queued for a GPU slot")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kernel", default=KERNEL)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="report the status and the decision, but never push",
    )
    args = ap.parse_args(argv)

    user, key = credentials()
    status = fetch_status(user, key)
    observed = status.get("status", "")
    message = status.get("failureMessage") or ""
    action = decide(observed)

    print(f"kernel : {args.kernel}")
    print(f"status : {observed!r}")
    if message:
        print(f"detail : {message.strip()[:300]}")
    print(f"action : {action}")

    if action == "noop":
        print("nothing to do: the run is in flight or already completed")
        return 0

    if args.dry_run:
        print("--dry-run: would re-push the current notebook to re-queue a GPU run")
        return 1

    return repush(args.kernel)


if __name__ == "__main__":
    raise SystemExit(main())
