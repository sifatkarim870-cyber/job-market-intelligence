"""Hugging Face corpus self-consistency checks. Read-only; no database needed.

Why this is separate from verify_local_hf_parity.py
---------------------------------------------------
Parity compares HF against the laptop's PostgreSQL, and the laptop is not
reachable from a GitHub runner -- so parity can never run in CI. That is the
real reason there was no automated gate: the one script that would have caught
a bad merge key could not run anywhere but one machine.

So this script covers the half that IS checkable remotely, and it is the one
that belongs in a scheduled workflow. Every check here corresponds to a failure
this project has actually had, or to a class of failure that would be silent:

  1. every enabled source has a shard      -- "built, seeded, working locally,
                                              but nothing was ever published"
  2. every shard matches SHARD_COLUMNS      -- a SELECT/column-list mismatch
                                              writes valid-but-shifted Parquet
                                              and nothing else notices
  3. the state/ seed snapshot is complete   -- CI seeds its throwaway database
                                              from this; if it is stale or
                                              partial, every scrape silently
                                              runs against the wrong reference
                                              data and still reports success
  4. the pg_dump sha256 verifies            -- otherwise the documented restore
                                              path does not actually restore
  5. the translations overlay is non-empty  -- it has been 0 bytes and the run
                                              still said "done"

Run:  uv run python scripts/verify_hf_corpus.py
Exit: 0 all checks pass, 1 something is wrong.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
from dataclasses import dataclass, field

import pyarrow.parquet as pq
import requests
from huggingface_hub import HfApi, HfFileSystem

REPO = os.environ.get("CORPUS_HF_REPO", "Shifat2110724169/job-market-intel-corpus")
TRANSLATIONS_REPO = os.environ.get(
    "CORPUS_HF_TRANSLATIONS_REPO", "Shifat2110724169/job-market-intel-translations"
)
STATE_DIR = "state/"
SOURCES_JSON = pathlib.Path(__file__).resolve().parents[1] / "config" / "sources.json"

#: Fraction of rows allowed to be duplicated between merges before
#: check_no_duplicate_identities() calls it a failure.
DUPLICATE_RATIO_LIMIT = 0.15


def _resolve_token() -> str | None:
    for var in ("CORPUS_HF_TOKEN", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        val = os.environ.get(var)
        if val and val.strip():
            return val.strip()
    for path in (
        pathlib.Path(os.environ["CORPUS_HF_TOKEN_FILE"])
        if os.environ.get("CORPUS_HF_TOKEN_FILE")
        else None,
        pathlib.Path(__file__).resolve().parents[2] / "Hugging_Face_token.txt",
    ):
        if path and path.exists():
            token = path.read_text(encoding="utf-8").strip()
            if token:
                return token
    return None


@dataclass
class Report:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))

    @property
    def failed(self) -> list[tuple[str, bool, str]]:
        return [c for c in self.checks if not c[1]]

    def render(self) -> str:
        width = max((len(c[0]) for c in self.checks), default=10)
        lines = []
        for name, ok, detail in self.checks:
            lines.append(f"  [{'OK' if ok else 'FAIL'}] {name:<{width}}  {detail}")
        passed = len(self.checks) - len(self.failed)
        lines.append("")
        lines.append(f"  {passed}/{len(self.checks)} checks passed")
        return "\n".join(lines)


def expected_columns() -> list[str]:
    """The shard schema, read from the exporter itself.

    Imported rather than duplicated so a change to SHARD_COLUMNS is picked up
    here automatically. A copy in this file would drift and then "verify" the
    wrong thing.
    """
    from job_market_intel.corpus.shard_export import SHARD_COLUMNS

    return list(SHARD_COLUMNS) + ["origin"]


def enabled_sources() -> list[str]:
    if not SOURCES_JSON.exists():
        return []
    data = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
    sources = data["sources"] if isinstance(data, dict) and "sources" in data else data
    return [s["code"] for s in sources if s.get("enabled")]


def check_sources_have_shards(files: list[str], report: Report) -> None:
    on_hf = {
        f.split("source=", 1)[1].split("/", 1)[0]
        for f in files
        if f.startswith("shards/") and ".parquet" in f
    }
    enabled = enabled_sources()
    missing = sorted(set(enabled) - on_hf)
    extra = sorted(on_hf - set(enabled))
    report.add(
        "every enabled source has a shard",
        not missing,
        f"{len(on_hf)} shards for {len(enabled)} enabled sources"
        + (f"; MISSING {missing}" if missing else ""),
    )
    if extra:
        print(f"  note: shards present for sources not enabled: {extra}")


def check_shard_schema(files: list[str], report: Report, token: str | None) -> int:
    """Every shard must carry exactly the exporter's column list.

    Metadata only -- pyarrow reads the Parquet footer in parallel threads,
    so this costs a range request per file rather than a full download.
    """
    import concurrent.futures

    expected = expected_columns()
    fs = HfFileSystem(token=token)
    shards = sorted(f for f in files if f.startswith("shards/") and f.endswith(".parquet"))
    bad: list[str] = []
    total = 0

    def _check_one(path: str) -> tuple[str, int, list[str] | None, Exception | None]:
        try:
            with fs.open(f"datasets/{REPO}/{path}", "rb") as fh:
                pf = pq.ParquetFile(fh)
                return path, pf.metadata.num_rows, list(pf.schema_arrow.names), None
        except Exception as exc:  # noqa: BLE001
            return path, 0, None, exc

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(_check_one, shards))

    for path, rows, names, exc in results:
        if exc is not None:
            bad.append(f"{path}: unreadable ({type(exc).__name__})")
            continue
        total += rows
        if names != expected:
            missing = [c for c in expected if c not in names]
            extra = [c for c in (names or []) if c not in expected]
            bad.append(f"{path}: missing={missing} extra={extra}")

    report.add(
        "shard schema matches exporter",
        not bad,
        f"{len(shards)} shards, {total:,} rows" + ("" if not bad else f"; {len(bad)} mismatched"),
    )
    for entry in bad[:5]:
        print(f"    {entry}")
    return total


def check_state_snapshot(files: list[str], report: Report) -> None:
    """CI seeds its throwaway database from state/; a broken seed is silent."""
    state_files = [f for f in files if f.startswith(STATE_DIR)]
    missing_schema = "state/schema.sql" not in files
    ref_parquets = [f for f in state_files if f.endswith(".parquet")]
    problems = []
    if missing_schema:
        problems.append("state/schema.sql missing")
    if not ref_parquets:
        problems.append("no state/*.parquet reference data")
    report.add(
        "state/ seed snapshot complete",
        not problems,
        f"{len(ref_parquets)} reference parquets"
        + ("" if not problems else "; " + ", ".join(problems)),
    )


def check_dumps(files: list[str], report: Report) -> None:
    """Verify every sha256 that has a matching dump alongside it."""
    dumps = [f for f in files if f.startswith("dumps/") and f.endswith(".dump")]
    if not dumps:
        report.add("pg_dump present", False, "no dumps/*.dump on HF")
        return
    verified, skipped, broken = [], [], []
    for dump in dumps:
        digest_file = f"{dump}.sha256"
        if digest_file not in files:
            skipped.append(dump)
            continue
        try:
            url = f"https://huggingface.co/datasets/{REPO}/resolve/main/{digest_file}"
            expected = requests.get(url, timeout=60).text.split()[0].lower()
            url = f"https://huggingface.co/datasets/{REPO}/resolve/main/{dump}"
            h = hashlib.sha256()
            with requests.get(url, timeout=600, stream=True) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=1 << 20):
                    h.update(chunk)
            (verified if h.hexdigest() == expected else broken).append(dump)
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{dump} ({type(exc).__name__})")
    report.add(
        "pg_dump sha256 verifies",
        not broken,
        f"{len(verified)} verified, {len(skipped)} without a digest, {len(broken)} broken"
        + ("" if not broken else "; " + ", ".join(broken)),
    )


def check_translations(report: Report, token: str | None) -> None:
    """The overlay has shipped empty while the kernel reported success."""
    try:
        fs = HfFileSystem(token=token)
        with fs.open(f"datasets/{TRANSLATIONS_REPO}/translations.parquet", "rb") as fh:
            pf = pq.ParquetFile(fh)
            rows, cols = pf.metadata.num_rows, list(pf.schema_arrow.names)
        required = {"key", "source_code", "source_job_id", "title_en", "description_en"}
        missing = sorted(required - set(cols))
        ok = rows > 0 and not missing
        report.add(
            "translations overlay non-empty",
            ok,
            f"{rows:,} rows, {len(cols)} cols" + ("" if not missing else f"; missing {missing}"),
        )
    except Exception as exc:  # noqa: BLE001
        report.add(
            "translations overlay non-empty", False, f"{type(exc).__name__}: {str(exc)[:60]}"
        )


def check_no_duplicate_identities(files: list[str], report: Report, token: str | None) -> None:
    """The natural key must be ~unique across the whole shard tree.

    Not entirely unique, and that is expected. CI publishes incremental shards
    named for their timestamp (``part-<ts>.parquet``) while the laptop's full
    export writes ``part-0.parquet`` covering everything. Between a CI publish
    and the next nightly merge both are present and the rows they share appear
    twice -- 2,062 duplicated identities across 33 files on 2026-10-13, about
    1.7% of rows, so a plain ``count(*)`` returned 119,343 instead of 117,281.

    So the ratio is always reported, and this fails only past
    :data:`DUPLICATE_RATIO_LIMIT`. A consumer who counts rows without
    deduplicating is over-counting during the window; a ratio climbing toward
    the limit means the nightly merge has stopped running entirely -- which is
    the single point of failure this project has no other way to detect.
    """
    import concurrent.futures

    fs = HfFileSystem(token=token)
    shards = sorted(f for f in files if f.startswith("shards/") and f.endswith(".parquet"))

    def _read_keys(path: str) -> tuple[str, int, set[tuple[str, str, str]], Exception | None]:
        try:
            with fs.open(f"datasets/{REPO}/{path}", "rb") as fh:
                table = pq.read_table(fh, columns=["source_job_id", "posting_date"])
            source = path.split("source=", 1)[1].split("/", 1)[0]
            local_keys = set()
            for sid, pdate in zip(
                table.column("source_job_id").to_pylist(),
                table.column("posting_date").to_pylist(),
                strict=False,
            ):
                local_keys.add((source, str(sid), str(pdate)[:10]))
            return path, table.num_rows, local_keys, None
        except Exception as exc:  # noqa: BLE001
            return path, 0, set(), exc

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(_read_keys, shards))

    for path, _, _, exc in results:
        if exc is not None:
            report.add(
                "natural key ~unique across shards",
                False,
                f"{path} unreadable: {type(exc).__name__}",
            )
            return

    total = sum(r[1] for r in results)
    keys: set[tuple[str, str, str]] = set().union(*(r[2] for r in results))

    extra = total - len(keys)
    ratio = extra / total if total else 0.0
    ok = ratio <= DUPLICATE_RATIO_LIMIT
    detail = f"{total:,} rows, {len(keys):,} distinct"
    if extra:
        detail += f"; {extra:,} duplicated ({ratio:.1%})"
        detail += (
            f" > {DUPLICATE_RATIO_LIMIT:.0%} -- the nightly merge is not running"
            if not ok
            else " (normal merge window)"
        )
    report.add("natural key ~unique across shards", ok, detail)


def main() -> int:
    token = _resolve_token()
    api = HfApi(token=token)
    report = Report()

    try:
        files = api.list_repo_files(REPO, repo_type="dataset")
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: cannot list {REPO}: {exc}")
        return 1

    print(f"corpus repo: {REPO}  ({len(files)} files)\n")

    check_sources_have_shards(files, report)
    check_shard_schema(files, report, token)
    check_no_duplicate_identities(files, report, token)
    check_state_snapshot(files, report)
    check_dumps(files, report)
    check_translations(report, token)

    print(report.render())
    print(
        "\nRESULT:",
        "corpus self-consistent" if not report.failed else "PROBLEMS -- see FAIL above",
    )
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
