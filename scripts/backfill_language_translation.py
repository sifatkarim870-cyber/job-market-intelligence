"""Backfill language_code + title translation for NULL language_code rows.

Reads existing job_title from core.jobs, runs language detection + NLLB
translation directly (no HTTP fetching, no page parsing), and updates the
database. Much faster than running the full HTML scraper pipeline.

Uses batched translation (translate_batch) for speed: groups rows by
detected language, then translates all titles for a language in a single
batched generate() call.

Usage:
    uv run python scripts/backfill_language_translation.py --limit 5000
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from loguru import logger
from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.normalization.translation import (
    NllbTranslator,
    TranslationSettings,
    detect_language,
    looks_like_non_english_output,
    resolve_flores_code,
)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill language detection + title translation for NULL language_code rows")
    ap.add_argument("--limit", type=int, default=None, help="Max rows to process")
    args = ap.parse_args()

    settings = TranslationSettings()
    translator = NllbTranslator(settings)

    with get_session() as session:
        rows = session.execute(
            text(
                "SELECT j.job_id, j.job_title, jd.description_clean "
                "FROM core.jobs j "
                "LEFT JOIN core.job_descriptions jd ON jd.job_id=j.job_id AND jd.posting_date=j.posting_date "
                "WHERE j.language_code IS NULL AND j.job_title IS NOT NULL "
                "ORDER BY j.job_id"
                + (f" LIMIT {args.limit}" if args.limit else "")
            )
        ).all()

        logger.info(f"Found {len(rows)} rows with NULL language_code and non-null job_title")

        # Step 1: Detect language for all rows
        detected_map: dict[int, str] = {}
        for job_id, job_title, description_clean in rows:
            probe = description_clean if description_clean and len(description_clean) >= 60 else job_title
            detected = detect_language(probe)
            if detected is None:
                detected = "unknown"
            detected_map[job_id] = detected

        # Step 2: Bucket non-English, mappable rows by FLORES code and batch-translate
        processed = 0
        counts = Counter()
        buckets: dict[str, list[tuple[int, str]]] = {}

        for job_id, job_title, description_clean in rows:
            detected = detected_map[job_id]
            if detected == "en":
                session.execute(
                    text("UPDATE core.jobs SET language_code = 'en', updated_at = now() WHERE job_id = :jid"),
                    {"jid": job_id},
                )
                counts["detected_english"] += 1
                processed += 1
                continue
            flores = resolve_flores_code(detected)
            if flores is None:
                counts["recorded_unresolved"] += 1
                session.execute(
                    text("UPDATE core.jobs SET language_code = :lc, updated_at = now() WHERE job_id = :jid"),
                    {"lc": detected, "jid": job_id},
                )
                processed += 1
                continue
            buckets.setdefault(flores, []).append((job_id, job_title))

        # Batch translate by language
        for flores, jobs in buckets.items():
            for start in range(0, len(jobs), 64):
                slab = jobs[start : start + 64]
                texts = [t for _, t in slab]
                outputs = translator.translate_batch(texts, flores, batch_size=64)
                for (job_id, _), en in zip(slab, outputs):
                    if not en or looks_like_non_english_output(en):
                        counts["recorded_unresolved"] += 1
                        session.execute(
                            text("UPDATE core.jobs SET language_code = :lc, updated_at = now() WHERE job_id = :jid"),
                            {"lc": detected_map[job_id], "jid": job_id},
                        )
                    else:
                        session.execute(
                            text(
                                "UPDATE core.jobs SET language_code = :lc, job_title_en = :te, "
                                "translated_by = :tb, updated_at = now() WHERE job_id = :jid"
                            ),
                            {
                                "lc": detected_map[job_id],
                                "te": en,
                                "tb": translator.provenance_label,
                                "jid": job_id,
                            },
                        )
                        counts["titles_translated"] += 1
                    processed += 1
                    if processed % 25 == 0:
                        session.commit()
                        logger.info(f"Committed after {processed} rows")

        session.commit()
        logger.info(f"Title pass complete: {processed} rows processed")
        logger.info(f"Counts: {dict(counts)}")

    return 0


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(main())
