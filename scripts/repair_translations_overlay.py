"""Rebuild the translations overlay as a UNION of an older revision and HEAD.

The incident
------------
``upload_overlay()`` in the Kaggle kernel carried the docstring::

    'Write the overlay to the translations repo. Additive, never a rewrite.'

but its body serialised only the rows collected by the current run and
uploaded them to the single fixed path ``translations.parquet``. Every earlier
run's translations were discarded. On 2026-10-12 a successful GPU run published
9,331 rows and silently dropped 24,202 that were still required, taking the
overlay from 24,722 rows to 9,331.

Why nothing was permanently lost
--------------------------------
The overlay is a transport, not the store. ``apply_translations.py`` had already
merged those 24,202 rows into local Postgres, and every one of the lost keys was
verified present locally with ``description_en`` populated. So the repair here is
about consistency of the published dataset, not recovery.

Why a union, not a revert
-------------------------
Reverting to the older revision would discard the 8,811 genuinely new
translations that the run produced. The correct state is the union of both, keyed
on the natural identity ``(source_code, source_job_id)``, with the NEWER row
winning where a key appears in both -- a re-translated row should replace its
stale predecessor.

``job_id`` is never used as a key: it is a per-database sequence, so it is not
stable across the corpus and the overlay.

Usage:
    python scripts/repair_translations_overlay.py --dry-run
    python scripts/repair_translations_overlay.py --push
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

import duckdb

OVERLAY_REPO = "Shifat2110724169/job-market-intel-translations"
OVERLAY_FILE = "translations.parquet"

TOKEN_FILE = pathlib.Path(__file__).resolve().parents[2] / "Hugging_Face_token.txt"

#: One row per (source_code, source_job_id), HEAD winning.
#:
#: The two priority columns must have DIFFERENT names. An earlier draft used
#: ``priority`` for both the 0/1 literal and the row_number(), so DuckDB renamed
#: the second to ``priority_1`` and ``EXCLUDE (priority)`` / ``WHERE priority =
#: 1`` silently referred to the literal -- which discarded the entire older
#: revision and returned exactly HEAD's row count. Two distinct names remove the
#: ambiguity.
#:
#: Paths and the column projection are interpolated rather than bound: the
#: statement is spliced into COPY(...), where DuckDB does not accept parameters.
#:
#: ``SELECT *`` on both sides is deliberately avoided. A file published by an
#: earlier buggy merge carries the bookkeeping column ``src_priority``, and
#: re-merging it raises "UNION ALL BY NAME ... src_priority occurs multiple
#: times". Projecting an explicit column list makes the repair idempotent no
#: matter what state the inputs are in.
MERGE_SQL = """
SELECT * EXCLUDE (rn, src_priority) FROM (
    SELECT *, row_number() OVER (
        PARTITION BY source_code, source_job_id ORDER BY src_priority DESC
    ) AS rn
    FROM (
        SELECT {cols}, 0 AS src_priority FROM read_parquet('{older}')   -- older revision
        UNION ALL BY NAME
        SELECT {cols}, 1 AS src_priority FROM read_parquet('{head}')    -- HEAD
    )
)
WHERE rn = 1
"""

#: Never treated as data: bookkeeping columns this script or its predecessors
#: may have leaked into a published file.
INTERNAL_COLUMNS = ("rn", "src_priority", "priority")


def column_list(con: duckdb.DuckDBPyConnection, path: pathlib.Path) -> str:
    """Comma-quoted real columns of ``path``, with any leaked helpers dropped."""
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{path.as_posix()}'").fetchall()]
    keep = [c for c in cols if c not in INTERNAL_COLUMNS]
    if not keep:
        raise SystemExit(f"{path} has no real columns; refusing to guess")
    return ", ".join(f'"{c}"' for c in keep)


def token() -> str:
    value = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not value.startswith("hf_"):
        raise SystemExit(f"{TOKEN_FILE} does not look like an HF token")
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--older", required=True, help="commit id of the pre-incident revision")
    ap.add_argument("--push", action="store_true", help="upload the merged file (default: dry run)")
    args = ap.parse_args(argv)

    from huggingface_hub import HfApi, hf_hub_download

    tok = token()
    api = HfApi(token=tok)
    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_overlay_"))

    paths = {}
    for label, rev in (("older", args.older), ("head", None)):
        path = hf_hub_download(
            OVERLAY_REPO, OVERLAY_FILE, repo_type="dataset", token=tok, revision=rev
        )
        paths[label] = pathlib.Path(path)
        print(f"  {label:5} {rev or 'HEAD':12} {pathlib.Path(path).stat().st_size:>12,}b")

    con = duckdb.connect()
    older_rows, = con.execute(
        f"SELECT count(*) FROM read_parquet('{paths['older'].as_posix()}')"
    ).fetchone()
    head_rows, = con.execute(
        f"SELECT count(*) FROM read_parquet('{paths['head'].as_posix()}')"
    ).fetchone()

    # The invariant the incident violated: a published overlay may never shrink.
    union_all = older_rows + head_rows
    print(f"\n  older={older_rows:,}  head={head_rows:,}  sum={union_all:,}")

    out = work / "merged.parquet"
    sql = MERGE_SQL.format(
        cols=column_list(con, paths["older"]),
        older=paths["older"].as_posix(),
        head=paths["head"].as_posix(),
    )
    con.execute(f"COPY ({sql}) TO '{out.as_posix()}' (FORMAT PARQUET)")
    merged, = con.execute(f"SELECT count(*) FROM '{out.as_posix()}'").fetchone()

    # The invariant that must hold: one output row per distinct natural key
    # across BOTH inputs. Checking `merged >= max(inputs)` is not enough --
    # a merge that silently returns only HEAD satisfies it exactly -- so the
    # expected count is computed from the inputs and compared for equality.
    expected, = con.execute(f"""
        SELECT count(*) FROM (
            SELECT source_code, source_job_id FROM '{paths["older"].as_posix()}'
            UNION
            SELECT source_code, source_job_id FROM '{paths["head"].as_posix()}'
        )
    """).fetchone()

    dupes, = con.execute(
        f"SELECT count(*) - count(DISTINCT (source_code, source_job_id)) "
        f"FROM '{out.as_posix()}'"
    ).fetchone()
    print(f"  merged={merged:,}   expected={expected:,}   duplicate keys={dupes}")

    if merged != expected:
        raise SystemExit(
            f"refusing to publish: merged {merged:,} rows but the two revisions "
            f"hold {expected:,} distinct natural keys. The merge dropped keys."
        )
    if merged < max(older_rows, head_rows):
        raise SystemExit(
            f"refusing to publish: merged ({merged:,}) is smaller than the larger "
            f"input ({max(older_rows, head_rows):,}); that is the exact regression "
            "being repaired"
        )
    if dupes:
        raise SystemExit(f"refusing to publish: {dupes} duplicate natural keys remain")

    # Every column the consumer expects must survive the union, and the merge's
    # internal bookkeeping columns must NOT: leaking src_priority into the
    # published file makes the next merge fail, because
    # "UNION ALL BY NAME does not support duplicate names -- src_priority
    # occurs multiple times".
    have = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{out.as_posix()}'").fetchall()}
    need = {"key", "lang", "source_code", "source_job_id", "title_en", "description_en"}
    internal = {"rn", "src_priority", "priority"}
    if missing := need - have:
        raise SystemExit(f"refusing to publish: merged file lost columns {sorted(missing)}")
    if leaked := internal & have:
        raise SystemExit(
            f"refusing to publish: merge bookkeeping columns {sorted(leaked)} leaked "
            "into the published file and would break the next merge"
        )

    if not args.push:
        print(f"\n--dry run: nothing uploaded. Merged file at {out}")
        return 0

    print(f"\nuploading {merged:,} rows to {OVERLAY_REPO}")
    api.upload_file(
        path_or_fileobj=str(out),
        path_in_repo=OVERLAY_FILE,
        repo_id=OVERLAY_REPO,
        repo_type="dataset",
    )
    print("uploaded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
