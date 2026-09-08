"""Manual entry point to run the company-alias candidate-generation batch
job (Step 25).

Scans every pair of ``core.companies`` rows, finds pairs whose
``normalized_name`` trigram similarity meets the configured threshold,
and writes proposed aliases to ``core.company_aliases`` for later human
review (see ``scripts/review_company_aliases.py``). Never merges
companies, never touches ``core.jobs.company_id`` -- see
``normalization/company_resolution.py``'s module docstring for the full,
confirmed design decisions this script relies on.

This is a separate batch job, not part of any scraper pipeline -- run it
manually after new companies have been ingested, or wire it into
``scheduler/`` as its own scheduled job once validated against more real
data.

Usage:
    python scripts/run_company_resolution_batch.py [--dry-run] [--threshold 0.5]
"""

from __future__ import annotations

import argparse

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.db.session import get_session
from job_market_intel.normalization import (
    apply_alias_candidates,
    build_alias_candidates,
    fetch_alias_candidate_pairs,
    get_company_resolution_settings,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Company Alias Candidate-Generation Batch Job")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Find and report alias candidates without writing any "
            "core.company_aliases or audit.change_log rows."
        ),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help=(
            "Override the configured similarity_threshold (0-1) for this "
            "run only, without changing .env."
        ),
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    resolution_settings = get_company_resolution_settings()
    if args.threshold is not None:
        resolution_settings = resolution_settings.model_copy(
            update={"similarity_threshold": args.threshold}
        )

    logger.info(
        "Starting company resolution batch (similarity_threshold={}, dry_run={}).",
        resolution_settings.similarity_threshold,
        args.dry_run,
    )

    with get_session() as session:
        pairs = fetch_alias_candidate_pairs(session, settings=resolution_settings)
        candidates = build_alias_candidates(pairs)

        applied = 0
        if not args.dry_run:
            applied = apply_alias_candidates(session, candidates)
        # Dry-run: nothing was written, so exiting the `with` block
        # cleanly still commits a no-op transaction -- fine, since
        # fetch_alias_candidate_pairs only reads.

    print()
    print("=" * 70)
    print("COMPANY ALIAS CANDIDATE GENERATION — RUN SUMMARY")
    print("=" * 70)
    print(f"Similarity threshold:        {resolution_settings.similarity_threshold}")
    print(f"Candidate pairs found:       {len(candidates)}")
    if args.dry_run:
        print("DRY-RUN MODE: no core.company_aliases rows were written.")
    else:
        print(f"Candidate pairs recorded:    {applied}")
        print("core.companies.is_verified was NOT changed by this run.")
        print("Review pending candidates with scripts/review_company_aliases.py.")
    print()

    if candidates:
        print("Candidates:")
        for candidate in candidates:
            print(
                f"  '{candidate.alias_company_name}' (company_id={candidate.alias_company_id}) "
                f"-> canonical '{candidate.canonical_company_name}' "
                f"(company_id={candidate.canonical_company_id}) "
                f"[similarity={candidate.similarity_score:.2f}]"
            )
        print()

    print("=" * 70)

    logger.info(
        "Company resolution batch finished: {} pairs found, {} recorded.",
        len(candidates),
        applied,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
