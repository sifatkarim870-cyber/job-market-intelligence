"""Backfill language_code + title translation for NULL language_code rows.

Reads existing job_title from core.jobs, runs language detection + NLLB
translation directly (no HTTP fetching, no page parsing), and updates the
database. Much faster than running the full HTML scraper pipeline.

Optimizations:
1. Preloads known title translations from core.jobs (instant cache hit for 2k+ rows).
2. Limits language detection probe to 1,000 characters for high detection throughput (~160 rows/s).
3. Deduplicates unique (flores, job_title) pairs before running NLLB model inference.
4. Includes posting_date in UPDATE predicate for direct partition targeting on core.jobs.
5. Performs bulk batch updates for English rows and translated rows.

Usage:
    uv run python scripts/backfill_language_translation.py
    uv run python scripts/backfill_language_translation.py --limit 500
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import psycopg
from psycopg.rows import dict_row

from job_market_intel.normalization.translation import (
    NllbTranslator,
    TranslationSettings,
    detect_language,
    looks_like_non_english_output,
    resolve_flores_code,
)

DB_URL = "postgresql://app_user:changeme@localhost:5432/job_market_intelligence"


def load_translation_cache(conn) -> dict[tuple[str, str], tuple[str, str]]:
    """Loads existing (language_code, job_title) -> (job_title_en, translated_by) cache."""
    cache: dict[tuple[str, str], tuple[str, str]] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT job_title, language_code, job_title_en, translated_by
            FROM core.jobs
            WHERE language_code IS NOT NULL AND job_title_en IS NOT NULL
            """
        )
        for title, lang, title_en, trans_by in cur.fetchall():
            if title and lang and title_en:
                cache[(lang, title)] = (title_en, trans_by or "pre_existing")
    return cache


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill language detection + title translation for NULL language_code rows")
    ap.add_argument("--limit", type=int, default=None, help="Max rows to process")
    ap.add_argument("--batch-size", type=int, default=32, help="NLLB inference batch size")
    args = ap.parse_args()

    t0 = time.time()
    print("=" * 70)
    print("STARTING LANGUAGE DETECTION & TITLE TRANSLATION BACKFILL")
    print(f"Limit: {args.limit or 'ALL remaining rows'}")
    print("=" * 70)

    with psycopg.connect(DB_URL) as conn:
        print("Loading translation cache from existing jobs...")
        cache = load_translation_cache(conn)
        print(f"  Loaded {len(cache):,} cached title translations in {time.time() - t0:.1f}s")

        # Fetch candidate rows
        limit_sql = f"LIMIT {args.limit}" if args.limit else ""
        query = f"""
            SELECT j.job_id, j.posting_date, j.job_title, jd.description_clean
            FROM core.jobs j
            LEFT JOIN core.job_descriptions jd ON jd.job_id = j.job_id AND jd.posting_date = j.posting_date
            WHERE j.language_code IS NULL AND j.job_title IS NOT NULL
            ORDER BY j.job_id, j.posting_date
            {limit_sql}
        """
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query)
            rows = cur.fetchall()

    total_rows = len(rows)
    print(f"Found {total_rows:,} candidate rows with NULL language_code.")
    if total_rows == 0:
        print("No rows to process.")
        return 0

    # Step 1: Detect language
    print("\n[Step 1/3] Detecting language across candidates...")
    t_detect = time.time()
    detected_list: list[dict] = []
    lang_counter = Counter()

    for idx, r in enumerate(rows, 1):
        desc = r["description_clean"]
        title = r["job_title"]
        probe = desc[:1000] if desc and len(desc) >= 60 else title
        detected = detect_language(probe) or "unknown"
        lang_counter[detected] += 1
        detected_list.append({
            "job_id": r["job_id"],
            "posting_date": r["posting_date"],
            "job_title": title,
            "detected_lang": detected,
        })
        if idx % 2500 == 0 or idx == total_rows:
            rate = idx / (time.time() - t_detect)
            print(f"  [{idx:>6,}/{total_rows:,}] detected ({rate:.0f} rows/s)")

    print("Language distribution detected:")
    for lang, cnt in lang_counter.most_common(12):
        print(f"  {lang:<8}: {cnt:>6,} ({cnt * 100 / total_rows:5.1f}%)")

    # Step 2: Separate English, Cache Hits, and Rows Needing Translation
    print("\n[Step 2/3] Categorizing rows & checking cache...")
    english_rows: list[tuple[int, object]] = []
    cached_trans_rows: list[tuple[str, str, str, int, object]] = []
    unresolved_rows: list[tuple[str, int, object]] = []
    need_translation: dict[str, list[dict]] = {}  # flores -> list of dicts

    counts = Counter()

    for item in detected_list:
        jid = item["job_id"]
        pdate = item["posting_date"]
        title = item["job_title"]
        lang = item["detected_lang"]

        if lang == "en":
            english_rows.append((jid, pdate))
            counts["english"] += 1
            continue

        # Check cache
        if (lang, title) in cache:
            title_en, trans_by = cache[(lang, title)]
            cached_trans_rows.append((lang, title_en, trans_by, jid, pdate))
            counts["cache_hit"] += 1
            continue

        flores = resolve_flores_code(lang)
        if flores is None:
            unresolved_rows.append((lang, jid, pdate))
            counts["unresolved_flores"] += 1
            continue

        need_translation.setdefault(flores, []).append(item)

    print(f"  English rows (no trans needed) : {len(english_rows):,}")
    print(f"  Cache hits (instant title)     : {len(cached_trans_rows):,}")
    print(f"  Unresolved FLORES code         : {len(unresolved_rows):,}")
    pending_count = sum(len(v) for v in need_translation.values())
    print(f"  Needing NLLB translation       : {pending_count:,} across {len(need_translation)} languages")

    # Immediate DB write for English, Cache Hits, and Unresolved
    print("\nWriting English, Cache Hits, and Unresolved rows to DB...")
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            if english_rows:
                cur.executemany(
                    "UPDATE core.jobs SET language_code = 'en', updated_at = now() WHERE job_id = %s AND posting_date = %s",
                    english_rows,
                )
            if cached_trans_rows:
                cur.executemany(
                    """
                    UPDATE core.jobs SET
                        language_code = %s,
                        job_title_en = %s,
                        translated_by = %s,
                        updated_at = now()
                    WHERE job_id = %s AND posting_date = %s
                    """,
                    cached_trans_rows,
                )
            if unresolved_rows:
                cur.executemany(
                    "UPDATE core.jobs SET language_code = %s, updated_at = now() WHERE job_id = %s AND posting_date = %s",
                    unresolved_rows,
                )
            conn.commit()
    print("  Instant updates committed.")

    # Step 3: Run NLLB translation for remaining rows
    if need_translation:
        print("\n[Step 3/3] Initializing NLLB model for remaining translations...")
        settings = TranslationSettings()
        translator = NllbTranslator(settings)

        t_trans = time.time()
        translated_count = 0

        # Sort languages by volume descending
        sorted_languages = sorted(need_translation.items(), key=lambda kv: len(kv[1]), reverse=True)

        for flores, job_items in sorted_languages:
            lang_code = job_items[0]["detected_lang"]
            print(f"\nTranslating {len(job_items):,} titles for {lang_code} (FLORES: {flores})...")

            # Deduplicate unique titles for this language
            unique_titles = list(dict.fromkeys(item["job_title"] for item in job_items))
            print(f"  Unique titles to translate: {len(unique_titles):,} (saving {len(job_items) - len(unique_titles):,} redundant translations)")

            # Batch translate unique titles
            title_translations: dict[str, str] = {}
            for start in range(0, len(unique_titles), args.batch_size):
                slab = unique_titles[start : start + args.batch_size]
                outputs = translator.translate_batch(slab, flores, batch_size=args.batch_size)
                for raw_title, en_trans in zip(slab, outputs):
                    title_translations[raw_title] = en_trans

                done_unique = min(start + args.batch_size, len(unique_titles))
                print(f"    Translated {done_unique:>5,}/{len(unique_titles):,} unique titles...", end="\r", flush=True)
            print()

            # Prepare DB updates for this language
            db_updates_success: list[tuple[str, str, str, int, object]] = []
            db_updates_fallback: list[tuple[str, int, object]] = []

            for item in job_items:
                raw_title = item["job_title"]
                jid = item["job_id"]
                pdate = item["posting_date"]
                en_title = title_translations.get(raw_title, "")

                if not en_title or looks_like_non_english_output(en_title):
                    db_updates_fallback.append((lang_code, jid, pdate))
                    counts["non_english_output"] += 1
                else:
                    db_updates_success.append((lang_code, en_title, translator.provenance_label, jid, pdate))
                    # Also update memory cache
                    cache[(lang_code, raw_title)] = (en_title, translator.provenance_label)
                    counts["titles_translated"] += 1

            # Commit updates for this language
            with psycopg.connect(DB_URL) as conn:
                with conn.cursor() as cur:
                    if db_updates_success:
                        cur.executemany(
                            """
                            UPDATE core.jobs SET
                                language_code = %s,
                                job_title_en = %s,
                                translated_by = %s,
                                updated_at = now()
                            WHERE job_id = %s AND posting_date = %s
                            """,
                            db_updates_success,
                        )
                    if db_updates_fallback:
                        cur.executemany(
                            "UPDATE core.jobs SET language_code = %s, updated_at = now() WHERE job_id = %s AND posting_date = %s",
                            db_updates_fallback,
                        )
                    conn.commit()

            translated_count += len(job_items)
            rate = translated_count / (time.time() - t_trans)
            print(f"  Committed {len(job_items):,} rows ({translated_count:,}/{pending_count:,} total done at {rate:.1f} rows/s)")

    print("\n" + "=" * 70)
    print(f"TRANSLATION BACKFILL COMPLETE in {time.time() - t0:.1f}s")
    print("Final Breakdown:")
    for k, v in counts.items():
        print(f"  {k:<25}: {v:>6,}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
