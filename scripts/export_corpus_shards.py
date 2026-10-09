"""CLI: export one source's new rows to a Hugging Face Parquet shard.

Called by CI as the last step of every scrape job, and usable by hand for a
backfill:

    python scripts/export_corpus_shards.py --source glints
    python scripts/export_corpus_shards.py --all
    python scripts/export_corpus_shards.py --source glints --since 2026-10-01T00:00:00Z
    python scripts/export_corpus_shards.py --all --dry-run
    python scripts/export_corpus_shards.py --source glints --strict

Fails OPEN by default: Hugging Face problems are reported and the exit code
stays 0, because a corpus export must not turn a successful scrape red. Pass
``--strict`` for a non-zero exit when debugging locally.

That promise has to cover import errors too. The first CI run failed with
``ModuleNotFoundError: No module named 'pyarrow'`` and exited 1 -- the failure
happened while importing this script, long before export_source's try/except
could see it. So the heavy imports are deferred into _main(), and the outermost
handler below turns anything that still escapes into a logged warning.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback


def _all_sources() -> list[str]:
    # get_session() is a @contextmanager wrapping a session. Calling execute()
    # on it directly raises AttributeError('_GeneratorContextManager' object has
    # no attribute 'execute') -- which is exactly what the first CI run did,
    # because --all is the only path that touches this function.
    from sqlalchemy import text

    from job_market_intel.db.session import get_session

    with get_session() as session:
        rows = session.execute(text("SELECT source_code FROM ref.sources ORDER BY 1")).all()
        return [r[0] for r in rows]


def _main() -> int:
    from loguru import logger

    from job_market_intel.common.config import get_settings
    from job_market_intel.common.logger import configure_logging
    from job_market_intel.corpus import CorpusSettings, export_source, fetch_rows
    from job_market_intel.db.engine import get_engine

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="source_code to export (e.g. glints)")
    parser.add_argument("--all", action="store_true", help="export every source in ref.sources")
    parser.add_argument("--since", help="ISO watermark override; ignores the stored one")
    parser.add_argument("--repo", help="override CORPUS_HF_REPO")
    parser.add_argument("--max-rows", type=int, help="override CORPUS_MAX_ROWS_PER_SHARD")
    parser.add_argument("--dry-run", action="store_true", help="print counts, upload nothing")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero on failure instead of failing open (default: fail open)",
    )
    args = parser.parse_args()

    if not args.source and not args.all:
        parser.error("one of --source or --all is required")

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    overrides: dict = {}
    if args.repo:
        overrides["hf_repo"] = args.repo
    if args.max_rows:
        overrides["max_rows_per_shard"] = args.max_rows
    corpus = CorpusSettings(**overrides)

    sources = _all_sources() if args.all else [args.source]
    engine = get_engine()

    print(f"repo    : {corpus.hf_repo}")
    print(f"sources : {len(sources)}")
    print("=" * 72)

    if args.dry_run:
        total = 0
        for code in sources:
            found = fetch_rows(engine, code, args.since, corpus.max_rows_per_shard)
            total += len(found)
            print(f"  {code:<14} {len(found):>7,} rows would be exported")
        print(f"  {'TOTAL':<14} {total:>7,} rows")
        return 0

    summaries = [export_source(engine, code, corpus) for code in sources]
    for s in summaries:
        marker = "OK " if s.get("uploaded") else "-- "
        detail = s.get("error") or s.get("skipped") or ""
        kib = round(s.get("bytes", 0) / 1024)
        print(f"{marker}{s['source']:<14} rows={s['rows']:>6,}  {kib:>8} KiB  {detail}")

    print("=" * 72)
    print(
        json.dumps(
            {
                "uploaded_shards": sum(1 for s in summaries if s.get("uploaded")),
                "rows_exported": sum(s["rows"] for s in summaries),
                "errors": [s for s in summaries if s.get("error")],
            },
            indent=2,
        )
    )
    logger.info("corpus export finished")
    return 1 if args.strict and any(s.get("error") for s in summaries) else 0


def main() -> int:
    """Outermost guard so an import or config error also fails open."""
    strict = "--strict" in sys.argv[1:]
    try:
        return _main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - see module docstring
        traceback.print_exc()
        print(f"\ncorpus export failed and was swallowed (fail-open): {exc}", file=sys.stderr)
        return 1 if strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
