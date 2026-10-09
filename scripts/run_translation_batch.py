"""Entry point for the translation batch: detect language, translate to English.

See ``normalization/translation.py``'s module docstring for the full design
(why a batch and not inline, why local NLLB, the two idempotent passes, and
the documented limitations). This script is the CLI wrapper: it selects rows
by column state, runs detection + NLLB, writes results atomically per row,
and prints a summary. Safe to re-run at any time -- completed rows are never
re-selected (``language_code``/``*_en`` IS NULL predicates do the filtering).

Usage:
    python scripts/run_translation_batch.py [--dry-run]
                                            [--scope {titles,descriptions,both}]
                                            [--limit N]

Scope notes:
    titles        detection + title translation only (the CI step in
                  classify_titles.yml runs this; ~1-2s per non-English
                  title on CPU).
    descriptions  the description pass only (run locally against Neon --
                  NLLB on CPU is far too slow for a 20-minute CI job at
                  description volume; one-time backfill plus new rows).
    both          detection+titles first, then descriptions (the default).
"""

from __future__ import annotations

import argparse
from collections import Counter

from loguru import logger

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.db.session import get_session
from job_market_intel.normalization.translation import (
    NllbTranslator,
    TranslationSettings,
    apply_description_translation,
    apply_title_translation,
    choose_detection_text,
    detect_language,
    fetch_description_pending,
    fetch_detection_pending,
    looks_like_non_english_output,
    process_description_row,
    process_detection_row,
    resolve_flores_code,
)

#: Rows written between commits -- bounds re-work after an interruption
#: (uncommitted rows are simply retried next run).
_COMMIT_EVERY_TITLES = 25
_COMMIT_EVERY_DESCRIPTIONS = 5

#: Descriptions translated together in one batched generate call.
_DESC_BATCH_JOBS = 8

#: How many real translations a --dry-run previews (keeps dry runs fast:
#: detection is cheap, model inference is not).
_DRY_RUN_TITLE_SAMPLES = 5
_DRY_RUN_DESC_SAMPLES = 3


def _run_title_pass(
    session,
    translator: NllbTranslator,
    *,
    dry_run: bool,
    limit: int | None,
) -> Counter:
    pending = fetch_detection_pending(session, limit=limit)
    counts: Counter = Counter()
    samples = 0

    for index, job in enumerate(pending, start=1):
        if not dry_run:
            payload = process_detection_row(job, translator)
            apply_title_translation(session, job.job_id, payload)
            if payload["language_code"] == "en":
                counts["detected_english"] += 1
            elif payload["job_title_en"]:
                counts["titles_translated"] += 1
            else:
                counts["recorded_unresolved"] += 1
            if index % _COMMIT_EVERY_TITLES == 0:
                session.commit()
                logger.info("Title pass: committed after {} rows.", index)
            continue

        # Dry run: detection for every row, full translation for a few.
        probe = choose_detection_text(job.job_title, job.description_clean)
        detected = detect_language(probe) or "unknown"
        counts[f"dry_detect_{detected}"] += 1
        flores = resolve_flores_code(detected)
        if flores and samples < _DRY_RUN_TITLE_SAMPLES:
            preview = translator.translate(job.job_title, flores)
            logger.info(
                "DRY-RUN sample job {}: {!r} [{}] -> {!r}",
                job.job_id,
                job.job_title,
                detected,
                preview,
            )
            samples += 1

    if pending and not dry_run:
        session.commit()
    counts["title_pass_rows"] = len(pending)
    return counts


def _run_description_pass(
    session,
    translator: NllbTranslator,
    *,
    dry_run: bool,
    limit: int | None,
) -> Counter:
    pending = fetch_description_pending(session, limit=limit)
    counts: Counter = Counter()
    samples = 0

    if dry_run:
        # Same preview-one-row-at-a-time path as before: a handful of
        # samples is kept deliberately small, so there is no win from
        # batching here and keeping the old code is safer.
        for index, job in enumerate(pending, start=1):
            if samples >= _DRY_RUN_DESC_SAMPLES:
                counts["description_pass_rows"] = len(pending)
                counts["descriptions_skipped_dry_run_cap"] = len(pending) - index + 1
                return counts

            description_en = process_description_row(job, translator, dry_run=dry_run)
            if description_en:
                counts["descriptions_translated"] += 1
            samples += 1
        counts["description_pass_rows"] = len(pending)
        return counts

    # Non-dry-run: batch rows by source language, then run chunks through
    # ``translate_batch`` -- the batched path that cuts per-row Python +
    # GPU-warmup overhead on CPU.
    buckets: dict[str, list] = {}
    for job in pending:
        if not job.description_clean:
            continue
        flores = resolve_flores_code(job.language_code or "")
        if flores is None:
            continue
        buckets.setdefault(flores, []).append(job)

    _translate_description_buckets(session, translator, buckets, counts, dry_run=False)
    counts["description_pass_rows"] = len(pending)
    return counts


def _translate_description_buckets(
    session,
    translator: NllbTranslator,
    buckets: dict[str, list],
    counts: Counter,
    *,
    dry_run: bool = False,
) -> int:
    """Translate description_clean for the row buckets one slice at a time.

    Every bucket carries rows for one source FLORES language so they can
    share the tokenizer's ``src_lang`` for the slice. Rows with an empty
    description or an unknown FLORES code were already dropped before
    bucketing by the caller.
    """
    rows_processed = 0
    for _flores, jobs in buckets.items():
        for start in range(0, len(jobs), _DESC_BATCH_JOBS):
            slab = jobs[start : start + _DESC_BATCH_JOBS]
            texts = [job.description_clean or "" for job in slab]
            outputs = translator.translate_batch(texts, _flores, batch_size=_DESC_BATCH_JOBS)
            for job, en in zip(slab, outputs, strict=True):
                rows_processed += 1
                if not en or looks_like_non_english_output(en):
                    logger.warning(
                        "job {}: translated description is not English (starts {!r}) -- skipped.",
                        job.job_id,
                        (en or "")[:60],
                    )
                    continue
                apply_description_translation(session, job.job_id, en)
                counts["descriptions_translated"] += 1
                if rows_processed % _COMMIT_EVERY_DESCRIPTIONS == 0:
                    session.commit()
                    logger.info("Description pass: committed after {} rows.", rows_processed)
        if not dry_run:
            session.commit()
    return rows_processed


def main() -> int:
    parser = argparse.ArgumentParser(description="Translation batch job (to English)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect languages and preview a few translations without writing any columns.",
    )
    parser.add_argument(
        "--scope",
        choices=("titles", "descriptions", "both"),
        default="both",
        help="Which pass(es) to run (default: both = detection+titles, then descriptions).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max rows per pass (default: all pending).",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    logger.info(
        "Starting translation batch (dry_run={}, scope={}, limit={}).",
        args.dry_run,
        args.scope,
        args.limit,
    )

    translator = NllbTranslator(TranslationSettings())
    title_counts: Counter = Counter()
    description_counts: Counter = Counter()

    with get_session() as session:
        if args.scope in ("titles", "both"):
            title_counts = _run_title_pass(
                session, translator, dry_run=args.dry_run, limit=args.limit
            )
        if args.scope in ("descriptions", "both"):
            description_counts = _run_description_pass(
                session, translator, dry_run=args.dry_run, limit=args.limit
            )
        # Exiting the `with` block commits whatever the last periodic
        # commit didn't cover (a no-op when --dry-run wrote nothing).

    print()
    print("=" * 70)
    print("TRANSLATION (to English) — RUN SUMMARY")
    print("=" * 70)
    print(f"Engine:                     {translator.provenance_label}")
    print(f"Scope:                      {args.scope}")
    if title_counts:
        print(f"Title pass rows:            {title_counts['title_pass_rows']}")
        if args.dry_run:
            detections = {
                k.removeprefix("dry_detect_"): v
                for k, v in sorted(title_counts.items())
                if k.startswith("dry_detect_")
            }
            print(f"  detected (dry-run):       {detections}")
        else:
            print(f"  English (skipped):        {title_counts['detected_english']}")
            print(f"  titles translated:        {title_counts['titles_translated']}")
            print(f"  recorded, no mapping:     {title_counts['recorded_unresolved']}")
    if description_counts:
        print(f"Description pass rows:      {description_counts['description_pass_rows']}")
        print(f"  descriptions translated:  {description_counts['descriptions_translated']}")
    if args.dry_run:
        print("DRY-RUN MODE: no columns were written.")
    print("=" * 70)

    logger.info(
        "Translation batch finished: title_rows={}, titles_translated={}, "
        "description_rows={}, descriptions_translated={}.",
        title_counts["title_pass_rows"],
        title_counts["titles_translated"],
        description_counts["description_pass_rows"],
        description_counts["descriptions_translated"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
