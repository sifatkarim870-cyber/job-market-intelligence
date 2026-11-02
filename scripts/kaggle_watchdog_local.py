"""Local Kaggle translation watchdog: re-push when the scheduled run dies on CPU.

Why this exists
---------------
The daily Kaggle schedule for ``mskarim870/jmi-translate-hf`` fires at
~09:03 UTC, and every scheduled firing observed (2026-10-24 through -31) was
allocated a CPU-only slot -- ``{"torch": "2.11.0+cpu", "gpus": 0}`` -- where
the kernel's fail-fast guard aborts in ~10 seconds::

    SystemExit: no GPU allocated: Kaggle gave this session a CPU-only torch
    build. Re-run when a GPU slot is available.

Two things are broken by the schedule itself, not by the notebook:

* **GPU slot:** a manual ``kaggle kernels push`` **waits for a GPU** (3/3
  successes, v51/v53/v56 all ``gpus: 2``); a UI-scheduled session does not wait
  and starts on CPU when no T4 is free at 09:03 UTC.
* **docker_image:** the scheduled run reverts the saved metadata to the CPU-only
  ``kaggle-images/python`` image (``torch 2.11.0+cpu``). The notebook needs the
  CUDA BYOD image ``kaggle-private-byod/python``.

This script runs locally (residential IP, where the Kaggle API works). Kaggle
returns HTTP 403 only to GitHub Actions' datacenter IPs (verified on the Oct 31
CI run), so status, pull and push all work from here.

The decision uses two signals:

* **Kernel status** -- ``kaggle kernels status``. A run that is already
  ``QUEUED`` or ``RUNNING`` will publish on its own, so the watchdog no-ops.
  This matters because the daily task fires 17 minutes after the schedule while
  a healthy run's first checkpoint is ~25 minutes in; without the check the
  watchdog would start a second GPU session for work already happening.
* **Overlay freshness** -- the Hugging Face translations dataset is the system
  of record. If it was re-published today after the 09:03 UTC window opened,
  today's run succeeded. If it is stale and no run is in flight, the script
  re-pushes the current notebook via ``kaggle kernels push --accelerator
  NvidiaTeslaT4``, which queues for a GPU. Before pushing it restores the kernel
  metadata to the working configuration (enable_gpu=true,
  machine_shape=NvidiaTeslaT4, docker_image=CUDA BYOD, creds dataset source),
  because the schedule overwrites them, and refuses to push a notebook that
  still carries the anonymous ``hf://`` glob that caused the v58 HTTP 429.

The script imports only the standard library, because
``test_declared_dependencies.py`` audits every import in ``scripts/`` against
pyproject.toml and ``kaggle`` is deliberately not a project dependency. Run it
with the CLI provided at runtime::

    KAGGLE_USERNAME=... KAGGLE_KEY=... \
        uv run --with kaggle python scripts/kaggle_watchdog_local.py

Credentials come from ``KAGGLE_USERNAME``/``KAGGLE_KEY`` environment variables
or fall back to ``~/.kaggle/kaggle.json``. HF is read anonymously (the dataset
is public), so no HF token is needed for the staleness check.

Usage:
    python scripts/kaggle_watchdog_local.py
    python scripts/kaggle_watchdog_local.py --dry-run
    python scripts/kaggle_watchdog_local.py --kernel mskarim870/jmi-translate-hf
"""

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import json
import os
import pathlib
import re
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

#: How long after the schedule fires before a stale overlay counts as a
#: failure. The CPU-slot abort happens ~10 seconds in, so this is ample, and it
#: still lets the 09:20 UTC daily task remediate the same morning.
GRACE = _dt.timedelta(minutes=10)

#: Metadata values the schedule keeps overwriting. The watchdog restores them
#: before every re-push so the kernel runs on CUDA with the write token.
REQUIRED_META = {
    "enable_gpu": True,
    "machine_shape": "NvidiaTeslaT4",
    "docker_image": (
        "gcr.io/kaggle-private-byod/python@sha256:"
        "2757e0c7d1e0a9cb43da657b97e223c321a98f5014bdf64f44f2f6b083ad2b2f"
    ),
    "dataset_sources": ["mskarim870/jmi-translate-creds"],
}

#: A run in one of these states is already on Kaggle's side; re-pushing would
#: start a second GPU session for work that is already happening.
IN_FLIGHT = frozenset({"QUEUED", "RUNNING"})


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
        "no Kaggle credentials: set KAGGLE_USERNAME and KAGGLE_KEY, or place "
        "kaggle.json in ~/.kaggle"
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


def overlay_age_days(last_modified: _dt.datetime | None) -> int | None:
    """Whole days between the overlay's last publish and today, or None."""
    if last_modified is None:
        return None
    return (today_utc() - last_modified.date()).days


def schedule_due(now: _dt.datetime | None = None) -> bool:
    """True once today's schedule window plus GRACE has passed."""
    now = now or _dt.datetime.now(_dt.UTC)
    window = _dt.datetime.combine(now.date(), SCHEDULE_UTC, tzinfo=_dt.UTC) + GRACE
    return now >= window


def decide(
    fresh: bool,
    status: str = "UNKNOWN",
    age_days: int | None = 0,
    due: bool = True,
) -> str:
    """Map overlay staleness, kernel status and time of day to an action.

    Three guards, in order:

    * ``status`` -- a run that is already queued or running will publish on its
      own, and re-pushing would start a second GPU session for work already
      happening. The daily task fires 17 minutes after the schedule, while a
      healthy run's first checkpoint is ~25 minutes in.
    * ``fresh`` -- today's overlay was published after the window; nothing to do.
    * ``due`` -- before today's window opens, yesterday's overlay is *expected*
      to be the newest one. The logon trigger fires every time the laptop comes
      back, so without this a 09:00 local logon (03:00 UTC) would re-push every
      single morning. Only a backlog older than one day is remediated early.
    """
    if status in IN_FLIGHT:
        return "noop"
    if fresh:
        return "noop"
    if not due and (age_days is None or age_days <= 1):
        return "noop"
    return "repush"


def kernel_status(kernel: str) -> str:
    """The kernel's current Kaggle status, or 'UNKNOWN'.

    Unlike the push and pull calls, this one works from the laptop -- Kaggle's
    API returns HTTP 403 only to datacenter IPs such as GitHub Actions'. A
    failure here is reported as UNKNOWN, which is treated as "not in flight",
    so a status hiccup cannot block remediation forever.
    """
    result = kaggle_cli("kernels", "status", kernel)
    text = f"{result.stdout or ''}{result.stderr or ''}"
    match = re.search(r"KernelWorkerStatus\.(\w+)", text)
    return match.group(1).upper() if match else "UNKNOWN"


def _verify_internal_calls(notebook_source: str) -> None:
    """Reject a notebook whose call sites disagree with its own definitions.

    v60 shipped a ``fetch_pending_retry`` whose signature dropped ``shards``
    but whose body still passed it: ``fetch_pending(con, offset, shards)``. The
    notebook parsed, every string the guard looked for was present, and it ran
    on a GPU for 264s before raising ``name 'shards' is not defined`` at the
    first fetch. No test caught it because none called ``fetch_pending_retry``.

    No string check can see that. Parsing can: a call to a function defined in
    the same cell with more positional arguments than that function accepts is
    a bug, whatever the surrounding text looks like.
    """
    try:
        tree = ast.parse(notebook_source)
    except SyntaxError as exc:
        raise SystemExit(f"pulled notebook does not parse ({exc}) -- not pushing")

    # name -> positional arity (None means *args, i.e. unlimited). Names with
    # two different signatures are skipped: a method and a module-level
    # function can share a name and guessing there would produce false alarms.
    signatures: dict[str, int | None] = {}
    ambiguous: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arity: int | None
        if node.args.vararg is not None:
            arity = None
        else:
            arity = len(node.args.posonlyargs) + len(node.args.args)
        if node.name in signatures:
            if signatures[node.name] != arity:
                ambiguous.add(node.name)
        else:
            signatures[node.name] = arity

    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        name = node.func.id
        if name in ambiguous:
            continue
        limit = signatures.get(name)
        if limit is None:  # unknown, or *args
            continue
        if any(isinstance(arg, ast.Starred) for arg in node.args):
            continue  # *xs can expand to any number
        if len(node.args) > limit:
            problems.append(
                f"line {node.lineno}: {name}() takes {limit} positional "
                f"argument(s) but is called with {len(node.args)}"
            )

    if problems:
        raise SystemExit(
            "pulled notebook has call sites that disagree with its own "
            "definitions (" + "; ".join(problems[:3]) + ") -- not pushing"
        )


def fix_and_verify_pulled(meta: dict, notebook_source: str) -> None:
    """Restore the working kernel metadata and verify the notebook source.

    The Kaggle schedule overwrites ``docker_image`` (to the CPU-only base
    image) and sometimes ``enable_gpu``/``machine_shape``. This restores them
    so the re-pushed kernel runs on CUDA with the write-token dataset.
    Refuses to push if the notebook source itself is degraded (missing
    find_token/upload_overlay, no known corpus-access strategy, the anonymous
    hf:// glob that caused the v58 HTTP 429, or a Neon reference) -- those are
    code problems the watchdog cannot fix by re-pushing.
    """
    dirty = False
    for field, expected in REQUIRED_META.items():
        if meta.get(field) != expected:
            print(f"fixing metadata: {field} {meta.get(field)!r} -> {expected!r}")
            meta[field] = expected
            dirty = True
    if dirty:
        print("metadata restored to working configuration")

    for required in (
        "def find_token",
        "def upload_overlay",
        "def main",
        "CANDIDATE_LABELS",
        "UNION ALL BY NAME",
        "fetch_pending_retry",
        "no new rows",
    ):
        if required not in notebook_source:
            raise SystemExit(
                f"pulled notebook missing {required!r} -- not pushing degraded code"
            )

    # Corpus access has two acceptable shapes, because the watchdog must be able
    # to repair whichever notebook is currently deployed -- refusing the one that
    # is live would leave the system unable to self-heal during a rollout.
    #
    #   v60: download the 0.56 GB corpus once, then page a materialised backlog.
    #   v59: list shards once and read them over authenticated hf://.
    #
    # Both avoid the v58 failure below; v60 also avoids the resolver quota.
    mirrored = ("def download_corpus", "snapshot_download", "def build_pending")
    streamed = ("def corpus_shards", "TYPE HUGGINGFACE")
    if not (all(f in notebook_source for f in mirrored)
            or all(f in notebook_source for f in streamed)):
        raise SystemExit(
            "pulled notebook has no known corpus-access strategy (neither "
            f"{mirrored} nor {streamed}) -- not pushing degraded code"
        )

    # A stale call site survives every string check above. v60 passed all of
    # them and still raised NameError 84s into a GPU run.
    _verify_internal_calls(notebook_source)

    if "hf_jjsMBFp" in notebook_source:
        raise SystemExit("pulled notebook still has hardcoded HF token -- not pushing")
    if "overlay_//file" in notebook_source:
        raise SystemExit("pulled notebook still has overlay_//file typo -- not pushing")
    if "SHARD_GLOBS" in notebook_source or "read_parquet([{globs}]" in notebook_source:
        # v58: DuckDB expands an hf:// glob with one tree-API call per
        # directory. This corpus has 540 of them, over Hugging Face's
        # 500-requests/300s anonymous budget, and the run died with HTTP 429
        # before translating a single row. Matched on the code (the SHARD_GLOBS
        # variable and the read_parquet call), not on the prose: the v59
        # docstring explains the bug and quotes the old glob on purpose.
        raise SystemExit(
            "pulled notebook still globs hf:// shards (540 tree-API calls -> "
            "HTTP 429) -- not pushing"
        )
    if "NEON_DATABASE_URL" in notebook_source:
        raise SystemExit("pulled notebook still references Neon -- not pushing")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kernel", default=KERNEL)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="report the staleness decision, but never push",
    )
    args = ap.parse_args(argv)

    credentials()  # preflight: fail before any network call if none are configured
    last_modified = hf_last_modified()
    status = kernel_status(args.kernel)
    fresh = overlay_is_fresh(last_modified)
    age = overlay_age_days(last_modified)
    due = schedule_due()
    action = decide(fresh, status, age, due)

    print(f"kernel : {args.kernel}")
    print(f"kernel status: {status}")
    print(f"hf overlay last_modified: {last_modified.isoformat() if last_modified else 'unreachable'}")
    print(f"overlay age: {age if age is not None else 'unknown'} day(s)")
    print(f"schedule window opened today at {SCHEDULE_UTC.isoformat()} UTC (due: {due})")
    print(f"overlay fresh: {fresh}")
    print(f"action : {action}")

    if action == "noop":
        if status in IN_FLIGHT:
            print(f"nothing to do: a run is already {status.lower()} on Kaggle")
        elif fresh:
            print("nothing to do: today's scheduled run already published translations")
        elif not due:
            print("nothing to do: today's schedule has not fired yet; "
                  "yesterday's overlay is expected")
        else:
            print("nothing to do")
        return 0

    if last_modified is None:
        print("refusing to re-push: hf unreachable, cannot confirm staleness")
        return 1

    if args.dry_run:
        print("--dry-run: would re-push the current notebook to re-queue a GPU run")
        return 1

    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_watchdog_local_"))
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
        fix_and_verify_pulled(meta, source)
    except SystemExit as exc:
        print(f"verification refused the push: {exc}")
        return 1

    # Persist the fixed metadata so the push saves the working configuration.
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(
        "pushing the current notebook (uploads AND runs; "
        "--accelerator queues for a GPU slot)"
    )
    result = kaggle_cli("kernels", "push", "-p", str(work), "--accelerator", "NvidiaTeslaT4")
    for stream in (result.stdout, result.stderr):
        for line in stream.splitlines():
            if line.strip():
                print(f"   {line.strip()}")
    if result.returncode != 0:
        print("re-push FAILED -- the kernel stays dead until the next watchdog run")
        return 1

    # Exit 1 on purpose: the scheduled run still failed today, and the non-zero
    # exit code is the notification (Task Scheduler will show it as a failure).
    # The re-push is remediation, not a clean bill of health.
    print("re-push accepted; the run is queued for a GPU slot")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
