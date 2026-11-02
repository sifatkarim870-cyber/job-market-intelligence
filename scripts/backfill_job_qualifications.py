"""Backfill education, experience, remote work type, and job category for existing jobs."""

import sys
import time
from sqlalchemy import create_engine, text
from job_market_intel.cleaning.qualification_mappers import (
    map_education_level,
    map_experience_level,
    map_remote_work_type,
    map_job_category,
)

DATABASE_URL = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"

def run_backfill(total_limit: int = 10000, batch_size: int = 2000):
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        edu_map = dict(conn.execute(text("SELECT code, education_level_id FROM ref.education_levels")).fetchall())
        exp_map = dict(conn.execute(text("SELECT code, experience_level_id FROM ref.experience_levels")).fetchall())
        remote_map = dict(conn.execute(text("SELECT code, remote_work_type_id FROM ref.remote_work_types")).fetchall())
        cat_map = dict(conn.execute(text("SELECT code, job_category_id FROM ref.job_categories")).fetchall())

    processed = 0
    total_updated = 0
    t0 = time.time()

    while processed < total_limit:
        cur_batch = min(batch_size, total_limit - processed)
        with engine.begin() as conn:
            query = text("""
                SELECT j.job_id, j.posting_date, j.job_title, l.raw_location_text, d.description_clean
                FROM core.jobs j
                LEFT JOIN core.job_descriptions d ON j.job_id = d.job_id AND j.posting_date = d.posting_date
                LEFT JOIN ref.locations l ON j.location_id = l.location_id
                WHERE (j.education_level_id IS NULL
                   AND j.experience_level_id IS NULL
                   AND j.remote_work_type_id IS NULL
                   AND j.job_category_id IS NULL)
                LIMIT :lim
            """)
            rows = conn.execute(query, {"lim": cur_batch}).fetchall()
            if not rows:
                print("No more candidate rows found.")
                break

            updates = []
            for r in rows:
                job_id, p_date, title, location, desc = r
                desc = desc or ""
                title = title or ""
                location = location or ""

                edu_code = map_education_level(desc)
                exp_code = map_experience_level(desc, title=title)
                remote_code = map_remote_work_type(location + " " + desc[:500])
                cat_code = map_job_category(title)

                edu_id = edu_map.get(edu_code) if edu_code else None
                exp_id = exp_map.get(exp_code) if exp_code else None
                remote_id = remote_map.get(remote_code) if remote_code else None
                cat_id = cat_map.get(cat_code) if cat_code else None

                if edu_id or exp_id or remote_id or cat_id:
                    updates.append({
                        "edu_id": edu_id,
                        "exp_id": exp_id,
                        "remote_id": remote_id,
                        "cat_id": cat_id,
                        "job_id": job_id,
                        "posting_date": p_date,
                    })

            if updates:
                conn.execute(text("""
                    UPDATE core.jobs
                    SET education_level_id = COALESCE(:edu_id, education_level_id),
                        experience_level_id = COALESCE(:exp_id, experience_level_id),
                        remote_work_type_id = COALESCE(:remote_id, remote_work_type_id),
                        job_category_id = COALESCE(:cat_id, job_category_id)
                    WHERE job_id = :job_id AND posting_date = :posting_date
                """), updates)

            total_updated += len(updates)
            processed += len(rows)
            elapsed = time.time() - t0
            print(f"Processed {processed}/{total_limit} rows: updated {total_updated} ({elapsed:.1f}s)")

if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    run_backfill(lim)
