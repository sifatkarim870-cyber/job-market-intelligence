"""Manual/CI entry point to run the title-classification batch job (Step 29).

Scans every job with ``title_classification_status IS NULL``, embeds its
title + a boilerplate-stripped description snippet using a local
multilingual sentence-embedding model, and matches it against the
curated ``ref.normalized_job_titles`` taxonomy -- or flags it as
non-job content via a narrow, confirmed-pattern deny-list. Never invents
new canonical titles -- see ``normalization/title_classification.py``'s
module docstring for the full confirmed design decisions this script
relies on.

CALIBRATION: ``--dry-run`` prints the real similarity-score distribution
for this run's jobs, not just match/no-match counts -- use this to
sanity-check ``MATCH_SIMILARITY_THRESHOLD`` against real data before
trusting it in production; that threshold is a documented starting
point, not yet calibrated (see the module docstring).

This is a separate batch job, not part of any scraper pipeline -- run it
manually after new jobs have been ingested, or via the scheduled
``.github/workflows/classify_titles.yml`` workflow.

Usage:
    python scripts/run_title_classification_batch.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys

from loguru import logger

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp1252 fix

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.db.session import get_session
from job_market_intel.normalization import (
    DEFAULT_CLASSIFIED_BY,
    apply_classifications_bulk,
    classify_jobs_batch,
    fetch_taxonomy,
    fetch_unclassified_jobs,
)

#: Rows written between commits -- bounds re-work after an interruption.
#: Bulk updates make a larger cadence cheap; 25 was the per-row era.
_COMMIT_EVERY = 500

#: Jobs embedded per pass. Encoding all 174k titles in one call peaked at
#: >4 GB and made progress invisible; 2k keeps memory flat and commits work
#: as it goes.
_CHUNK = 2_000


def main() -> int:
    parser = argparse.ArgumentParser(description="Title Classification Batch Job (Step 29)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Classify and report results, including the similarity-score "
            "distribution, without writing anything."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max jobs to process this run; 0 = all pending.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=3,
        help="Max CPU threads for embedding model (default: 3 = 25% of 12 cores).",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    # Bound PyTorch & BLAS CPU usage so the laptop remains responsive
    import os
    import torch
    max_threads = max(1, args.threads)
    torch.set_num_threads(max_threads)
    os.environ["OMP_NUM_THREADS"] = str(max_threads)
    os.environ["MKL_NUM_THREADS"] = str(max_threads)
    logger.info("Starting title classification batch (dry_run={}, max_threads={}/25% CPU).", args.dry_run, max_threads)

    # Imported here, matching normalization.title_classification's own
    # deferred import -- keeps this script's --help usable even in an
    # environment without sentence-transformers installed yet.
    from sentence_transformers import SentenceTransformer

    from job_market_intel.normalization.title_classification import DEFAULT_MODEL_NAME

    model = SentenceTransformer(DEFAULT_MODEL_NAME)

    with get_session() as session:
        taxonomy = fetch_taxonomy(session)
        if not taxonomy:
            logger.error(
                "ref.normalized_job_titles is empty -- run `python -m seed.run_all` first."
            )
            return 1

        taxonomy_texts = [entry.normalized_title for entry in taxonomy]
        taxonomy_embeddings = model.encode(taxonomy_texts, normalize_embeddings=True)

        jobs = fetch_unclassified_jobs(session)
        if args.limit:
            jobs = jobs[: args.limit]
            logger.info("--limit: processing only {} pending jobs", len(jobs))

        results: list[tuple] = []
        for job_start in range(0, len(jobs), _CHUNK):
            job_chunk = jobs[job_start : job_start + _CHUNK]
            chunk_results = classify_jobs_batch(
                job_chunk, taxonomy, taxonomy_embeddings, model
            )
            results.extend(zip(job_chunk, chunk_results, strict=True))

            if not args.dry_run:
                for start in range(0, len(chunk_results), _COMMIT_EVERY):
                    part = list(
                        zip(
                            job_chunk[start : start + _COMMIT_EVERY],
                            chunk_results[start : start + _COMMIT_EVERY],
                            strict=True,
                        )
                    )
                    apply_classifications_bulk(
                        session, part, classified_by_label=DEFAULT_CLASSIFIED_BY
                    )
                    session.commit()
            logger.info(
                "Title classification: {:,}/{:,} jobs processed.",
                min(job_start + _CHUNK, len(jobs)),
                len(jobs),
            )

    matched = [(j, r) for j, r in results if r.status == "matched"]
    no_match = [(j, r) for j, r in results if r.status == "no_match"]
    excluded = [(j, r) for j, r in results if r.status == "excluded_non_job"]
    taxonomy_by_id = {entry.normalized_title_id: entry.normalized_title for entry in taxonomy}

    print()
    print("=" * 70)
    print("TITLE CLASSIFICATION BATCH — RUN SUMMARY" + (" (DRY RUN)" if args.dry_run else ""))
    print("=" * 70)
    print(f"Jobs processed:    {len(results)}")
    print(f"  Matched:         {len(matched)}")
    print(f"  No match:        {len(no_match)}")
    print(f"  Excluded (non-job): {len(excluded)}")

    scored = [r.confidence for _, r in results if r.confidence is not None]
    if scored:
        print()
        print(f"Similarity score distribution (of {len(scored)} scored jobs):")
        print(
            f"  min={min(scored):.2f}  max={max(scored):.2f}  avg={sum(scored) / len(scored):.2f}"
        )

    if matched:
        print()
        print("Sample matches:")
        for job, result in matched[:10]:
            title = taxonomy_by_id.get(result.normalized_title_id, "?")
            print(f"  [{result.confidence:.2f}] {job.job_title!r} -> {title!r}")

    if excluded:
        print()
        print("Sample excluded (non-job content):")
        for job, _ in excluded[:10]:
            print(f"  {job.job_title!r}")

    print("=" * 70)

    logger.info("Title classification batch run finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
