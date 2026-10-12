"""Export untranslated rows for the Kaggle GPU kernel to translate.

Why this exists
---------------
Translation in this project runs along two paths, split by cost:

* **Titles** are translated on CPU by ``facebook/nllb-200-distilled-600M``
  inside ``classify_titles.yml`` (~1-2s per title, which fits a CI job).
* **Descriptions** are translated by a Kaggle kernel on GPU, which writes an
  overlay to ``Shifat2110724169/job-market-intel-translations``;
  ``apply_translations.py`` merges that overlay into Postgres.

The description path is a one-shot. Nothing pushed NEW rows to the kernel, so
the overlay stopped being regenerated and the corpus began drifting: as
scrapers append, every new non-English description is invisible to the
translator. This script is the missing upstream half -- it reads the corpus,
selects exactly what has no ``description_en`` yet, and writes a worklist the
kernel can pick up.

The loop, end to end::

    scrape --> local Postgres
                 |
                 |  this script (export_translation_worklist.py)
                 v
           HF: translations/worklist.parquet        <- Kaggle kernel reads this
                 |
                 |  kernel translates on GPU
                 v
           HF: translations/translations.parquet  <- kernel writes this
                 |
                 |  apply_translations.py
                 v
             local Postgres

Contract with the kernel
-----------------------
The output is written in the SAME shape the existing overlay uses, so the
kernel needs no change and ``apply_translations.py`` reads it unchanged:

    key             "<source_code>:<source_job_id>", NULL (see below)
    lang            target language, always "en"
    source_code     natural-key half 1
    source_job_id   natural-key half 2
    language_code   the DETECTED source language, e.g. "fa"
    title_en        NULL -- this worklist is description-only
    description_en  NULL -- filled in by the kernel
    method          NULL -- filled in by the kernel

Two deliberate choices, both matching the observed overlay:

``lang`` is the TARGET language, not the detected one. Every row in the live
overlay has ``lang = 'en'``, including the Persian and Georgian ones.

``key`` is left NULL. In the existing overlay, ``key`` is populated for exactly
the 1,424 ``copy_english`` rows and NULL for all 23,298 ``nllb`` rows -- it is
a leftover from an earlier dedup pass, not part of the join. The join is on
``(source_code, source_job_id)``. Populating it here would be harmless but
would imply the kernel depends on it.

Identity is the natural key, never ``job_id``: each database has its own
sequence, so local job 12345 and CI job 12345 are unrelated postings.

Safety
------
* ``--dry-run`` reports and writes nothing.
* Rows with no description at all are excluded -- there is nothing to
  translate, and emitting them would grow the worklist on every run with
  nothing ever completing.
* Output is published as a new dated file alongside the existing ones, never
  over the overlay itself: the kernel's output and this input are different
  artifacts and overwriting either loses work.

Usage:
    python scripts/export_translation_worklist.py --dry-run
    python scripts/export_translation_worklist.py
    python scripts/export_translation_worklist.py --min-length 200 --limit 5000
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import sys

from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

WORKLIST_REPO = "Shifat2110724169/job-market-intel-translations"
#: Prefix kept distinct from the kernel's output (``translations.parquet``) so
#: the two artifacts can coexist in one repo.
WORKLIST_PATH = "translations/worklist.parquet"

LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"

#: Descriptions shorter than this are a title, a "apply now" stub or a
#: contact block. Sending them to a 600M-parameter model on GPU costs minutes
#: per page and produces nothing useful.
DEFAULT_MIN_LENGTH = 40

#: Target language of every overlay row. See the module docstring: ``lang`` is
#: the target, not the detected source language.
TARGET_LANGUAGE = "en"

#: Matches SHARD_COLUMNS / the live overlay, so the kernel reads this with no
#: change and apply_translations.py accepts the result unchanged.
WORKLIST_COLUMNS = (
    "key",
    "lang",
    "source_code",
    "source_job_id",
    "language_code",
    "title_en",
    "description_en",
    "method",
)

#: Rows needing translation, in the overlay's own vocabulary.
#:
#: The description must EXIST. A non-English job with no description row has
#: nothing to translate, and including it would make the worklist grow without
#: bound as such rows accumulate -- every run re-emitting work that can never
#: complete. Measured 2026-10-12: all 64 such rows are `indeed` rows with no
#: description at all.
SELECT_WORKLIST = """
SELECT s.source_code,
       j.source_job_id::text AS source_job_id,
       COALESCE(j.language_code, 'und') AS language_code,
       d.description_clean       AS description
FROM core.jobs j
JOIN ref.sources s           ON s.source_id = j.source_id
JOIN core.job_descriptions d ON d.job_id = j.job_id
WHERE COALESCE(j.language_code, 'en') <> 'en'
  AND j.language_code IS NOT NULL
  AND d.description_en IS NULL
  AND d.description_clean IS NOT NULL
  AND length(d.description_clean) >= :min_length
ORDER BY s.source_code, j.source_job_id
"""


def _token() -> str:
    """HF write token from the environment, else the local token file."""
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        token = os.environ.get(name)
        if token:
            return token
    path = pathlib.Path(
        r"D:\Research_Project\JobMarketAnalysisPlatform\DataBase\Hugging_Face_token.txt"
    )
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    raise SystemExit(
        "no HF token: set HF_TOKEN, or place one at " + str(path)
    )


def fetch_worklist(
    engine, min_length: int = DEFAULT_MIN_LENGTH, limit: int | None = None
) -> list[tuple[str, str, str, str]]:
    """(source_code, source_job_id, language_code, description) needing work."""
    sql = SELECT_WORKLIST
    params: dict = {"min_length": min_length}
    if limit:
        sql += f" LIMIT {int(limit)}"
    with engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def build_table(rows: list[tuple[str, str, str, str]]):
    """Shape the worklist exactly like the existing overlay.

    ``key``, ``title_en``, ``description_en`` and ``method`` are left NULL: the
    first is unused by the join (see the module docstring), the second is not
    this worklist's job, and the last two are what the kernel fills in.
    """
    import pyarrow as pa

    return pa.table(
        {
            "key": pa.array([None] * len(rows), pa.string()),
            "lang": pa.array([TARGET_LANGUAGE] * len(rows), pa.string()),
            "source_code": pa.array([r[0] for r in rows], pa.string()),
            "source_job_id": pa.array([r[1] for r in rows], pa.string()),
            "language_code": pa.array([r[2] for r in rows], pa.string()),
            "title_en": pa.array([None] * len(rows), pa.string()),
            "description_en": pa.array([None] * len(rows), pa.string()),
            "method": pa.array([None] * len(rows), pa.string()),
        }
    )


def summarise(rows: list[tuple[str, str, str, str]], total_chars: int) -> str:
    """A per-source/per-language breakdown, so the log says what is queued."""
    by_source: dict[str, int] = {}
    by_lang: dict[str, int] = {}
    for code, _job_id, lang, _desc in rows:
        by_source[code] = by_source.get(code, 0) + 1
        by_lang[lang] = by_lang.get(lang, 0) + 1
    lines = [
        "  sources  : " + ", ".join(f"{k}={v}" for k, v in sorted(by_source.items())),
        "  languages: " + ", ".join(f"{k}={v}" for k, v in sorted(by_lang.items())),
        f"  payload  : {total_chars:,} chars (~{total_chars / 4:,} tokens)",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report only; upload nothing")
    ap.add_argument("--dsn", default=LOCAL_DSN)
    ap.add_argument("--repo", default=WORKLIST_REPO)
    ap.add_argument(
        "--min-length",
        type=int,
        default=DEFAULT_MIN_LENGTH,
        help=f"skip descriptions shorter than this (default {DEFAULT_MIN_LENGTH})",
    )
    ap.add_argument("--limit", type=int, help="cap rows this run (for testing)")
    args = ap.parse_args(argv)

    engine = create_engine(args.dsn)
    rows = fetch_worklist(engine, args.min_length, args.limit)

    if not rows:
        logger.info("nothing to translate: every non-English description has an English value")
        return 0

    total_chars = sum(len(r[3]) for r in rows)
    logger.info(
        "{} row(s) need translation, {} across the corpus",
        f"{len(rows):,}",
        f"{total_chars:,} chars",
    )
    logger.info("\n{}", summarise(rows, total_chars))

    if args.dry_run:
        logger.info("--dry-run: nothing uploaded")
        return 0

    import huggingface_hub
    import pyarrow.parquet as pq

    token = _token()
    work = pathlib.Path(
        __import__("tempfile").mkdtemp(prefix="jmi_worklist_")
    )
    local = work / "worklist.parquet"
    table = build_table(rows)
    pq.write_table(table, local, compression="zstd", compression_level=9)

    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    api = huggingface_hub.HfApi(token=token)
    # Dated copy first: the canonical worklist path is rewritten so the kernel
    # always has one obvious file to read, while each run is also kept for
    # audit. An upload failure part-way leaves the previous worklist intact.
    api.upload_file(
        path_or_fileobj=str(local),
        path_in_repo=WORKLIST_PATH,
        repo_id=args.repo,
        repo_type="dataset",
        commit_message=f"translation worklist {stamp}: {len(rows)} rows to translate",
    )
    api.upload_file(
        path_or_fileobj=str(local),
        path_in_repo=f"translations/worklist-{stamp}.parquet",
        repo_id=args.repo,
        repo_type="dataset",
        commit_message=f"translation worklist archive {stamp}: {len(rows)} rows",
    )

    size_kib = local.stat().st_size / 1024
    logger.info(
        "published {}/{} ({:.1f} KiB) -- the Kaggle kernel reads translations/worklist.parquet",
        args.repo,
        WORKLIST_PATH,
        size_kib,
    )
    logger.info(
        "next step: run the kernel, then apply its output with "
        "scripts/apply_translations.py"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
