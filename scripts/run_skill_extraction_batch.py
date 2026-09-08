"""Manual entry point to run the skill-extraction batch job (Step 26).

Scans every job with a description but no skills extracted yet (by this
extractor's ``extracted_by`` label), matches its
``core.job_descriptions.description_clean`` text against the curated
``ref.skills`` vocabulary, and writes matches to ``bridge.job_skills``.
Never creates new ``ref.skills`` rows -- see
``normalization/skill_extraction.py``'s module docstring for the full
confirmed design decisions this script relies on.

This is a separate batch job, not part of any scraper pipeline -- run it
manually after new jobs have been ingested, or wire it into
``scheduler/`` as its own scheduled job once validated against more real
data.

Usage:
    python scripts/run_skill_extraction_batch.py [--dry-run]
"""

from __future__ import annotations

import argparse

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.db.session import get_session
from job_market_intel.normalization import (
    DEFAULT_EXTRACTED_BY,
    apply_skill_extractions,
    build_term_index,
    extract_skill_ids,
    fetch_skill_vocabulary,
    fetch_unscanned_jobs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Skill Extraction Batch Job")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report matched skills without writing any bridge.job_skills rows.",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    logger.info("Starting skill extraction batch (dry_run={}).", args.dry_run)

    with get_session() as session:
        vocabulary = fetch_skill_vocabulary(session)
        short_terms, long_terms = build_term_index(vocabulary)
        jobs = fetch_unscanned_jobs(session, extracted_by_label=DEFAULT_EXTRACTED_BY)

        per_job_matches: list[tuple[int, set[int]]] = []
        applied = 0

        for job in jobs:
            skill_ids = extract_skill_ids(job.description_clean, short_terms, long_terms)
            per_job_matches.append((job.job_id, skill_ids))
            if skill_ids and not args.dry_run:
                applied += apply_skill_extractions(
                    session,
                    job_id=job.job_id,
                    posting_date=job.posting_date,
                    skill_ids=skill_ids,
                    extracted_by_label=DEFAULT_EXTRACTED_BY,
                )
        # Dry-run: nothing was written, so exiting the `with` block
        # cleanly still commits a no-op transaction -- fine, since this
        # loop only reads when --dry-run is set.

    skill_name_by_id = {entry.skill_id: entry.skill_name for entry in vocabulary}
    jobs_with_matches = sum(1 for _, skill_ids in per_job_matches if skill_ids)
    total_matches = sum(len(skill_ids) for _, skill_ids in per_job_matches)

    print()
    print("=" * 70)
    print("SKILL EXTRACTION — RUN SUMMARY")
    print("=" * 70)
    print(f"Jobs scanned:                 {len(jobs)}")
    print(f"Jobs with at least one match:  {jobs_with_matches}")
    print(f"Total skill matches found:    {total_matches}")
    if args.dry_run:
        print("DRY-RUN MODE: no bridge.job_skills rows were written.")
    else:
        print(f"bridge.job_skills rows inserted: {applied}")
    print()

    if per_job_matches:
        print("Sample matches (first 10 jobs with matches):")
        shown = 0
        for job_id, skill_ids in per_job_matches:
            if not skill_ids or shown >= 10:
                continue
            names = ", ".join(sorted(skill_name_by_id.get(sid, str(sid)) for sid in skill_ids))
            print(f"  job_id={job_id}: {names}")
            shown += 1
        print()

    print("=" * 70)

    logger.info(
        "Skill extraction batch finished: {} jobs scanned, {} matches found, {} rows inserted.",
        len(jobs),
        total_matches,
        applied,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
