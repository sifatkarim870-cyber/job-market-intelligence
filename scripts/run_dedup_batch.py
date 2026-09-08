"""Manual entry point to run the cross-source duplicate-detection batch job.

Scans every currently active, not-yet-flagged ``core.jobs`` row, finds
duplicate pairs posted under different sources within the configured
posting-date window (conservative title+company matching -- see
``normalization/dedup.py``'s module docstring for the confirmed design),
and sets ``core.jobs.is_duplicate_of`` accordingly.

This is a separate batch job, not part of any scraper pipeline (confirmed
design decision: dedup runs after ingestion, not inline during
``save_cleaned_job``) -- run it manually after a scrape, or wire it into
``scheduler/`` as its own scheduled job once Step 19 is verified against
real data.

Usage:
    python scripts/run_dedup_batch.py [--dry-run]
"""

from __future__ import annotations

import argparse

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.db.session import get_session
from job_market_intel.normalization import (
    apply_duplicate_matches,
    fetch_dedup_candidates,
    find_duplicate_matches,
    get_dedup_settings,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-Source Duplicate Detection Batch Job")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Find and report duplicate matches without writing any "
            "is_duplicate_of updates or audit.change_log rows."
        ),
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    dedup_settings = get_dedup_settings()
    logger.info(
        "Starting cross-source dedup batch (posting_date_window_days={}, dry_run={}).",
        dedup_settings.posting_date_window_days,
        args.dry_run,
    )

    with get_session() as session:
        candidates = fetch_dedup_candidates(session)
        matches = find_duplicate_matches(candidates, settings=dedup_settings)

        applied = 0
        if not args.dry_run:
            applied = apply_duplicate_matches(session, matches)
        # Dry-run: rolling back is unnecessary since nothing was written,
        # but exiting the `with` block cleanly still commits a no-op
        # transaction -- fine, since fetch_dedup_candidates only reads.

    print()
    print("=" * 70)
    print("CROSS-SOURCE DUPLICATE DETECTION — RUN SUMMARY")
    print("=" * 70)
    print(f"Active, unflagged jobs scanned: {len(candidates)}")
    print(f"Duplicate pairs found:          {len(matches)}")
    if args.dry_run:
        print("DRY-RUN MODE: no is_duplicate_of updates were written.")
    else:
        print(f"Duplicate pairs flagged:        {applied}")
    print()

    if matches:
        print("Matches:")
        for match in matches:
            marker = " [content_hash also matched]" if match.content_hash_matched else ""
            print(
                f"  job_id={match.duplicate_job_id} ({match.duplicate_source_code}) "
                f"-> canonical job_id={match.canonical_job_id} "
                f"({match.canonical_source_code}){marker}"
            )
        print()

    print("=" * 70)

    logger.info(
        "Dedup batch finished: {} candidates scanned, {} matches found, {} applied.",
        len(candidates),
        len(matches),
        applied,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
