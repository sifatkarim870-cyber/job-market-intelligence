"""
Backfill feature extractors for non-English rows.

Reads description_en / job_title_en translations already stored in the DB
and re-runs all qualification_mappers extractors over the translated text,
updating core.jobs columns:
  experience_years_min/max, seniority_role_type, is_managerial,
  work_schedule, skills_normalized, benefits_normalized,
  education_field_raw, education_field_normalized,
  education_level_id, experience_level_id

NOTE: education_field_raw/normalized are on core.jobs (NOT job_descriptions).
      education_level_id / experience_level_id are FK int IDs (not text codes).

Usage:
  uv run python scripts/backfill_feature_extractors.py
  uv run python scripts/backfill_feature_extractors.py --limit 500   # test sample
  uv run python scripts/backfill_feature_extractors.py --also-english # re-run on EN rows too
"""
import argparse
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp1252 fix

import psycopg
from psycopg.rows import dict_row

from job_market_intel.cleaning.qualification_mappers import (
    map_education_level,
    map_experience_level,
    extract_education_discipline_context,
    extract_experience_years,
    extract_seniority_and_management,
    extract_work_schedule,
    extract_normalized_skills,
    extract_normalized_benefits,
)

DB_URL = "postgresql://app_user:changeme@localhost:5432/job_market_intelligence"
BATCH_SIZE = 1_000

FETCH_SQL = """
SELECT
    j.job_id,
    j.posting_date,
    j.language_code,
    j.job_title,
    j.job_title_en,
    d.description_clean,
    d.description_en
FROM core.jobs j
JOIN core.job_descriptions d
    ON d.job_id = j.job_id AND d.posting_date = j.posting_date
WHERE
    {filter_clause}
ORDER BY j.job_id, j.posting_date
{limit_clause}
"""

UPDATE_JOBS_SQL = """
UPDATE core.jobs SET
    experience_years_min       = %(experience_years_min)s,
    experience_years_max       = %(experience_years_max)s,
    seniority_role_type        = %(seniority_role_type)s,
    is_managerial              = %(is_managerial)s,
    work_schedule              = %(work_schedule)s,
    skills_normalized          = %(skills_normalized)s,
    benefits_normalized        = %(benefits_normalized)s,
    education_field_raw        = %(education_field_raw)s,
    education_field_normalized = %(education_field_normalized)s,
    education_level_id         = %(education_level_id)s,
    experience_level_id        = %(experience_level_id)s,
    updated_at                 = now()
WHERE job_id = %(job_id)s AND posting_date = %(posting_date)s
"""


def load_ref_maps(conn) -> tuple[dict[str, int], dict[str, int]]:
    """Load code→id lookups for education_levels and experience_levels."""
    edu_map: dict[str, int] = {}
    exp_map: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT education_level_id, code FROM ref.education_levels")
        for eid, code in cur.fetchall():
            edu_map[code] = eid
        cur.execute("SELECT experience_level_id, code FROM ref.experience_levels")
        for xid, code in cur.fetchall():
            exp_map[code] = xid
    return edu_map, exp_map


def extract_all(title: str, text: str, edu_map: dict, exp_map: dict) -> dict:
    """Run all extractors and return a flat dict of extracted values."""
    exp_min, exp_max = extract_experience_years(text)
    seniority, is_mgr = extract_seniority_and_management(title, text)
    edu_field_raw, edu_field_norm = extract_education_discipline_context(text)

    edu_code = map_education_level(text)
    exp_code = map_experience_level(text, title)

    return {
        "experience_years_min": exp_min,
        "experience_years_max": exp_max,
        "seniority_role_type": seniority,
        "is_managerial": is_mgr,
        "work_schedule": extract_work_schedule(text),
        "skills_normalized": extract_normalized_skills(text),
        "benefits_normalized": extract_normalized_benefits(text),
        "education_field_raw": edu_field_raw,
        "education_field_normalized": edu_field_norm,
        "education_level_id": edu_map.get(edu_code) if edu_code else None,
        "experience_level_id": exp_map.get(exp_code) if exp_code else None,
    }


def run_backfill(limit: int | None = None, also_english: bool = False, step3_only: bool = False) -> None:
    if step3_only:
        filter_clause = "j.updated_at > now() - interval '4 hours'"
    elif also_english:
        filter_clause = "j.language_code IS NOT NULL AND (d.description_en IS NOT NULL OR j.job_title_en IS NOT NULL)"
    else:
        filter_clause = "j.language_code IS NOT NULL AND j.language_code != 'en' AND (d.description_en IS NOT NULL OR j.job_title_en IS NOT NULL)"

    limit_clause = f"LIMIT {limit}" if limit else ""
    sql = FETCH_SQL.format(filter_clause=filter_clause, limit_clause=limit_clause)

    t0 = time.time()
    total_fetched = 0
    total_updated = 0

    # Per-column non-null extraction counters
    col_changed: dict[str, int] = {
        "experience_years_min": 0,
        "experience_years_max": 0,
        "seniority_role_type": 0,
        "is_managerial": 0,
        "work_schedule": 0,
        "skills_normalized": 0,
        "benefits_normalized": 0,
        "education_field_raw": 0,
        "education_field_normalized": 0,
        "education_level_id": 0,
        "experience_level_id": 0,
    }

    # KEY FIX: use TWO separate connections.
    # Committing on the same connection that holds a named server-side cursor
    # causes psycopg3 to drop that cursor (cursors live inside a transaction).
    # read_conn: holds the streaming server-side cursor, never commits mid-stream.
    # write_conn: does all UPDATE + COMMIT operations independently.
    with psycopg.connect(DB_URL) as read_conn, psycopg.connect(DB_URL) as write_conn:
        edu_map, exp_map = load_ref_maps(read_conn)
        print(f"  Loaded ref maps: {len(edu_map)} education levels, {len(exp_map)} experience levels")

        batch_rows: list[dict] = []

        def flush_batch():
            nonlocal total_updated
            if not batch_rows:
                return
            with write_conn.cursor() as upd_cur:
                upd_cur.executemany(UPDATE_JOBS_SQL, batch_rows)
                total_updated += len(batch_rows)
            write_conn.commit()
            batch_rows.clear()

        # Server-side cursor streams rows without loading all into RAM.
        # read_conn stays in its transaction the whole time — no commits on it.
        with read_conn.cursor(name="backfill_cursor", row_factory=dict_row) as fetch_cur:
            fetch_cur.itersize = BATCH_SIZE
            fetch_cur.execute(sql)

            for row in fetch_cur:
                total_fetched += 1

                # Build full text: prefer translated version, append raw for extra signal
                desc_en = row["description_en"] or ""
                desc_raw = row["description_clean"] or ""
                title_en = row["job_title_en"] or ""
                title_raw = row["job_title"] or ""

                full_text = (desc_en + "\n\n" + desc_raw).strip() if desc_en else desc_raw
                full_title = (title_en + " / " + title_raw).strip(" /") if title_en else title_raw

                extracted = extract_all(full_title, full_text, edu_map, exp_map)

                for col in col_changed:
                    if extracted.get(col) is not None:
                        col_changed[col] += 1

                batch_rows.append({
                    "job_id": row["job_id"],
                    "posting_date": row["posting_date"],
                    **extracted,
                })

                if len(batch_rows) >= BATCH_SIZE:
                    flush_batch()
                    elapsed = time.time() - t0
                    rate = total_fetched / elapsed
                    print(
                        f"  [{total_fetched:>7,}] rows processed | "
                        f"{rate:.0f} rows/s | "
                        f"updated={total_updated:,}",
                        flush=True,
                    )

            flush_batch()  # final partial batch

    elapsed = time.time() - t0
    print("\n" + "=" * 65)
    print(f"BACKFILL COMPLETE — {elapsed:.1f}s")
    print(f"  Rows fetched   : {total_fetched:,}")
    print(f"  Rows updated   : {total_updated:,}")
    print(f"\nNon-null extractions per column (of {total_fetched:,} rows processed):")
    for col, cnt in col_changed.items():
        pct = cnt / total_fetched * 100 if total_fetched else 0
        print(f"  {col:<30} {cnt:>8,}  ({pct:5.1f}%)")
    print("=" * 65)


def main():
    parser = argparse.ArgumentParser(description="Backfill feature extractors for non-EN rows")
    parser.add_argument("--limit", type=int, default=None, help="Max rows to process (for testing)")
    parser.add_argument("--also-english", action="store_true", help="Also re-run on English rows")
    parser.add_argument("--step3-only", action="store_true", help="Process only recently updated Step 3 rows")
    args = parser.parse_args()

    if args.step3_only:
        mode = "Step 3 rows only (updated in last 4 hours)"
    elif args.also_english:
        mode = "ALL languages"
    else:
        mode = "non-English only"

    print(f"Starting backfill [{mode}] ...")
    if args.limit:
        print(f"  *** TEST MODE: limited to {args.limit:,} rows ***")

    run_backfill(limit=args.limit, also_english=args.also_english, step3_only=args.step3_only)


if __name__ == "__main__":
    main()
