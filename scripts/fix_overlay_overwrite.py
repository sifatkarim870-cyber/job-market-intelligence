"""Stop the Kaggle kernel from overwriting the translations overlay.

The bug
-------
``upload_overlay`` carried the docstring::

    'Write the overlay to the translations repo. Additive, never a rewrite.'

and its body did precisely the opposite. It registered only the rows collected
by the current run and uploaded them to the single fixed path
``translations.parquet``::

    con.register("overlay_arrow", pa.Table.from_pylist(rows))
    con.execute("COPY (SELECT * FROM overlay_arrow) TO 'overlay.parquet' ...")
    api.upload_file(path_or_fileobj=..., path_in_repo="translations.parquet", ...)

Because there is exactly one path, every upload replaced the whole dataset. On
2026-10-12 a successful GPU run published 9,331 rows and dropped 24,202 that
were still required, taking the overlay from 24,722 rows to 9,331. The run
reported success. Nothing warned, because nothing checked.

This is the same shape of bug as ``export_corpus_to_hf.py`` deleting every shard
it did not just write: an additive operation implemented as a full rewrite.

What this does
--------------
Replaces the function with a merge. The existing ``translations.parquet`` is
downloaded from the Hub, unioned with this run's rows, and de-duplicated on the
natural key ``(source_code, source_job_id)`` with THIS run winning -- so a
re-translated row replaces its stale predecessor instead of appearing twice.

Two assertions run before anything is published:

* ``merged == number of distinct natural keys across both inputs`` -- catches a
  merge that silently loses keys.
* ``merged >= rows already in the repo`` -- the direct regression guard.

The first assertion exists because the obvious ``merged >= max(inputs)`` check
is not sufficient: a merge that returns only HEAD satisfies it exactly. That is
precisely how a duplicate-column-name mistake in this same SQL survived review
here -- ``0 AS priority`` and ``row_number() ... AS priority`` collide, DuckDB
renames the second to ``priority_1``, and ``WHERE priority = 1`` then filters on
the literal. Hence two distinct column names (``src_priority``, ``rn``) and an
equality assertion rather than an inequality.

Which kernel
------------
``mskarim870/jmi-translate-hf`` is the SOURCE that ``port_kaggle_kernel_to_hf``
copies from, so it must be fixed first or the next port reverts the scheduled
kernel. ``--kernel`` accepts either.

Note that ``kaggle kernels push`` uploads AND runs, so pushing triggers a real
run. Dry run is the default.

Usage:
    python scripts/fix_overlay_overwrite.py --kernel mskarim870/jmi-translate-hf
    python scripts/fix_overlay_overwrite.py --kernel mskarim870/nllb-translate --push
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

NEW = '''def upload_overlay(con, rows):
    """Write the overlay, MERGING with what the repo already holds.

    The previous body said "Additive, never a rewrite" and then did a full
    rewrite: it serialised only this run's rows and uploaded them to the one
    fixed path translations.parquet, so every upload replaced the whole
    dataset. On 2026-10-12 that took the overlay from 24,722 rows to 9,331 and
    silently dropped 24,202 translations while the run still reported success.

    Now the existing file is read back, unioned with this run's rows, and
    de-duplicated on the natural key (source_code, source_job_id) with THIS
    run winning, so a re-translation replaces its stale predecessor.

    If the repository already holds translations.parquet and it cannot be read,
    this RAISES. It does not fall back to publishing this run's rows alone: that
    fallback is the overwrite bug itself. A first attempt used
    HfApi.download_repo_file, which does not exist in huggingface_hub at all, so
    the surrounding try/except swallowed an AttributeError and the kernel
    quietly published 9,331 rows in place of 33,533 -- a silent 24,202-row
    regression that the shrink guard below could not catch, because the failure
    path set prior_rows = 0 before reaching it. Losing a run's work is strictly
    better than destroying earlier runs' work, so the error is fatal.
    """
    import pyarrow as pa
    from huggingface_hub import HfApi, hf_hub_download

    token = find_token()
    api = HfApi(token=token)
    WORK.mkdir(parents=True, exist_ok=True)
    target = WORK / "overlay.parquet"

    con.register("new_overlay", pa.Table.from_pylist(rows))

    # Does the repo already hold an overlay? Asked separately from the download
    # so that "no prior file yet" (a legitimate first run) is distinguishable
    # from "the prior file exists but I could not read it" (fatal).
    try:
        remote_files = api.list_repo_files(OVERLAY_REPO_ID, repo_type="dataset")
    except Exception as exc:
        raise RuntimeError(
            f"cannot list files in {OVERLAY_REPO_ID} ({exc}); refusing to upload "
            "blindly, because publishing without reading the prior overlay is "
            "exactly how 24,202 translations were destroyed on 2026-10-12"
        ) from exc
    has_prior = "translations.parquet" in remote_files

    prior_rows = 0
    if has_prior:
        # hf_hub_download, not HfApi.download_repo_file -- the latter does not
        # exist in huggingface_hub and fails with AttributeError.
        downloaded = hf_hub_download(
            repo_id=OVERLAY_REPO_ID,
            filename="translations.parquet",
            repo_type="dataset",
            token=token,
        )
        prior = pathlib.Path(downloaded)
        prior_rows, = con.execute(
            f"SELECT count(*) FROM read_parquet('{prior.as_posix()}')"
        ).fetchone()
        log(f"prior overlay has {prior_rows} rows; merging this run's {len(rows)} in")
    else:
        log(f"{OVERLAY_REPO_ID} has no overlay yet; publishing this run's rows")

    if prior_rows:
        # src_priority and rn must not collide with any real column, and must
        # not collide with EACH OTHER. When both were named priority, DuckDB
        # renamed the second to priority_1 and the filter below silently
        # selected HEAD only -- a merge that looked like it worked.
        #
        # Both bookkeeping columns are EXCLUDED from the output. Publishing
        # src_priority would make the NEXT run fail outright with "UNION ALL BY
        # NAME ... src_priority occurs multiple times", because the column is
        # already present in the file being read back.
        con.execute(f"""
            COPY (
                SELECT * EXCLUDE (rn, src_priority) FROM (
                    SELECT *, row_number() OVER (
                        PARTITION BY source_code, source_job_id
                        ORDER BY src_priority DESC
                    ) AS rn
                    FROM (
                        SELECT *, 0 AS src_priority
                          FROM read_parquet('{prior.as_posix()}')
                        UNION ALL BY NAME
                        SELECT *, 1 AS src_priority FROM new_overlay
                    )
                ) WHERE rn = 1
            ) TO '{target.as_posix()}' (FORMAT PARQUET)
        """)
        expected, = con.execute(f"""
            SELECT count(*) FROM (
                SELECT source_code, source_job_id
                  FROM read_parquet('{prior.as_posix()}')
                UNION
                SELECT source_code, source_job_id FROM new_overlay
            )
        """).fetchone()
    else:
        con.execute(f"COPY new_overlay TO '{target.as_posix()}' (FORMAT PARQUET)")
        expected = len(rows)

    total, = con.execute(
        f"SELECT count(*) FROM '{target.as_posix()}'"
    ).fetchone()

    # The bookkeeping columns must not reach the Hub: src_priority left in the
    # published file makes the NEXT run's "UNION ALL BY NAME" fail with
    # "src_priority occurs multiple times", because the column is already there.
    cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{target.as_posix()}'").fetchall()}
    if leaked := {"rn", "src_priority"} & cols:
        raise RuntimeError(
            f"refusing to publish: bookkeeping columns {sorted(leaked)} leaked "
            "into the overlay and would break the next merge"
        )

    if total != expected:
        raise RuntimeError(
            f"overlay merge produced {total} rows but the inputs hold {expected} "
            "distinct natural keys; refusing to publish a lossy overlay"
        )
    if prior_rows and total < prior_rows:
        raise RuntimeError(
            f"refusing to publish {total} rows: the repo already holds {prior_rows}. "
            "A shrinking overlay is the 2026-10-12 regression."
        )

    api.create_repo(OVERLAY_REPO_ID, repo_type="dataset", exist_ok=True)
    api.upload_file(
        path_or_fileobj=str(target),
        path_in_repo="translations.parquet",
        repo_id=OVERLAY_REPO_ID,
        repo_type="dataset",
        token=token,
    )
    log(f"published {total} overlay rows ({len(rows)} new, {prior_rows} prior)")
    return total
'''

KERNEL = "mskarim870/nllb-translate"
HEAD = "def upload_overlay("

#: find_token iterates this tuple but must not define it: the constant has to
#: live in the notebook, because the notebook runs standalone. An earlier patch
#: referenced it without ever defining it, costing a full seven-minute run that
#: ended on its final line with "name 'CANDIDATE_LABELS' is not defined".
#: Re-inserted by patch() when a previous bad patch deleted it.
LABELS_CONST = '''#: Secret labels tried in order by find_token.
CANDIDATE_LABELS = ("hf_token.txt", "hf_token", "HUGGING_FACE_TOKEN", "huggingface_token")

'''


def kaggle(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "kaggle", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def code_of(nb: dict) -> str:
    return "\n".join(
        "".join(c["source"]) for c in nb.get("cells", []) if c.get("cell_type") == "code"
    )


def top_level_names(source: str) -> set[str]:
    """Every module-level name a cell defines.

    Used to prove the patch removed nothing but the body of upload_overlay.
    """
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def patch(nb_path: pathlib.Path) -> bool:
    """Swap upload_overlay for the merging version.

    The replaced span is located with **AST line numbers**, not by scanning for
    the next ``def`` at column 0. Two earlier attempts used text scanning and
    both destroyed neighbouring code:

    * stopping on any line beginning with ``# `` deleted ``main()`` outright;
    * stopping at the next column-0 ``def``/``class`` deleted the module-level
      ``CANDIDATE_LABELS = (...)`` assignment, which sits between
      ``upload_overlay`` and ``find_token``. That constant is referenced by
      find_token, so the kernel would have died with a NameError -- on the very
      next scheduled run.

    A module-level assignment is not a ``def``, so any text scan that stops at
    one is wrong. ``node.end_lineno`` is exact, and ``top_level_names`` then
    proves nothing else was lost.
    """
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    changed = False

    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell["source"])
        if HEAD not in source:
            continue

        # Idempotent only against the CORRECT merge. A kernel already carrying
        # the broken variant (the HfApi.download_repo_file spelling, or the
        # "publish this run's rows only" fallback) must be re-patched, because
        # that version destroys the overlay exactly as the original did.
        broken_markers = ("download_repo_file", "publishing this run's rows only")
        already_merged = "refusing to publish" in source and not any(
            m in source for m in broken_markers
        )
        if already_merged and "CANDIDATE_LABELS" not in source:
            # Already merged, but the constant a previous bad patch deleted has
            # to come back, or find_token raises NameError.
            anchor = source.index(HEAD)
            cell["source"] = [source[:anchor] + LABELS_CONST + source[anchor:]]
            nb_path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
            print("   merge already present; restored the deleted CANDIDATE_LABELS")
            return True
        if already_merged:
            print("   upload_overlay already merges correctly; nothing to do")
            return False
        if any(m in source for m in broken_markers):
            found = ", ".join(m for m in broken_markers if m in source)
            print(f"   found the BROKEN merge ({found}); re-patching")

        before_names = top_level_names(source)

        lines = source.splitlines(keepends=True)
        tree = ast.parse(source)
        target = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "upload_overlay"
        )
        # end_lineno is 1-based and inclusive; convert to a 0-based slice.
        head = "".join(lines[: target.lineno - 1])
        tail = "".join(lines[target.end_lineno :])

        patched = head + NEW + "\n\n" + tail
        compile(patched, "cell", "exec")

        after_names = top_level_names(patched)
        lost = before_names - after_names
        if lost:
            raise SystemExit(
                f"patch would delete top-level names {sorted(lost)}; refusing. "
                "The replacement must span upload_overlay's body and nothing else."
            )

        cell["source"] = [patched]
        changed = True

    if changed:
        nb_path.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    return changed


def defs_of(nb_path: pathlib.Path) -> set[str]:
    """Top-level function/class names in a notebook, read from its CODE cells."""
    src = code_of(json.loads(nb_path.read_text(encoding="utf-8")))
    return set(re.findall(r"(?m)^(?:def|class)\s+(\w+)", src))


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
    ap.add_argument("--kernel", default=KERNEL)
    ap.add_argument("--push", action="store_true", help="upload AND run (default: dry run)")
    ap.add_argument("--timeout", type=int, default=2400)
    args = ap.parse_args(argv)

    work = pathlib.Path(tempfile.mkdtemp(prefix="jmi_merge_"))
    result = kaggle("kernels", "pull", args.kernel, "-p", str(work), "-m")
    if result.returncode != 0:
        raise SystemExit(f"pull failed: {result.stderr.strip()[:300]}")

    nb = list(work.glob("*.ipynb"))[0]
    shutil.copyfile(nb, nb.with_suffix(".ipynb.bak"))
    before = defs_of(nb)
    print(f"pulled {args.kernel} -> {nb.name} ({nb.stat().st_size:,} bytes)")

    if not patch(nb):
        print("nothing to patch")
        return 0
    print(f"   rewrote upload_overlay as a merge; now {nb.stat().st_size:,} bytes")

    src = code_of(json.loads(nb.read_text(encoding="utf-8")))
    assert "NEON_DATABASE_URL" not in src
    sanity(src)
    after = defs_of(nb)
    lost = before - after
    print(f"sanity: compiles; functions lost={sorted(lost) or 'NONE'}")
    if lost:
        raise SystemExit(f"patch deleted {sorted(lost)}; refusing to push")

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
