"""Complete full backfill for empty columns in core.jobs:
- application_url & application_method ('external_url' / 'email')
- education_level_id, experience_level_id, remote_work_type_id, job_category_id
- visa_sponsorship, relocation_support
"""

import sys
import time
import psycopg
from job_market_intel.cleaning.qualification_mappers import (
    map_education_level,
    map_experience_level,
    map_remote_work_type,
    map_job_category,
    map_visa_sponsorship,
    map_relocation_support,
)

DATABASE_URL = "postgresql://app_user:changeme@localhost:5432/job_market_intelligence"

def run_full_backfill():
    write_conn = psycopg.connect(DATABASE_URL)
    write_conn.autocommit = True
    write_cur = write_conn.cursor()

    # Step 1: Backfill application_url & application_method
    print("--- Step 1: Checking application_url & application_method ---")
    write_cur.execute("SELECT count(*) FROM core.jobs WHERE application_url IS NOT NULL")
    app_count = write_cur.fetchone()[0]
    print(f"Jobs with application_url already populated: {app_count:,}")

    # Step 2: Fetch lookup maps
    print("\n--- Step 2: Loading lookup tables ---")
    write_cur.execute("SELECT code, education_level_id FROM ref.education_levels")
    edu_map = dict(write_cur.fetchall())
    write_cur.execute("SELECT code, experience_level_id FROM ref.experience_levels")
    exp_map = dict(write_cur.fetchall())
    write_cur.execute("SELECT code, remote_work_type_id FROM ref.remote_work_types")
    remote_map = dict(write_cur.fetchall())
    write_cur.execute("SELECT code, job_category_id FROM ref.job_categories")
    cat_map = dict(write_cur.fetchall())
    print(f"Loaded {len(edu_map)} edu, {len(exp_map)} exp, {len(remote_map)} remote, {len(cat_map)} cat lookups.")

    # Step 3: Stream and batch update qualification columns
    print("\n--- Step 3: Streaming jobs and descriptions for qualification extraction ---")
    
    write_cur.execute("""
        SELECT count(*) 
        FROM core.jobs j
        WHERE (j.education_level_id IS NULL
           OR j.experience_level_id IS NULL
           OR j.remote_work_type_id IS NULL
           OR j.job_category_id IS NULL
           OR j.visa_sponsorship IS NULL
           OR j.relocation_support IS NULL)
    """)
    target_count = write_cur.fetchone()[0]
    print(f"Total candidate rows needing qualification enrichment: {target_count:,}")

    # Open a dedicated read connection with a transaction block for the server-side cursor
    read_conn = psycopg.connect(DATABASE_URL)
    with read_conn.transaction():
        stream_cur = read_conn.cursor(name="job_qualification_stream")
        stream_cur.execute("""
            SELECT j.job_id, j.posting_date, j.job_title, l.raw_location_text, d.description_clean,
                   j.education_level_id, j.experience_level_id, j.remote_work_type_id, j.job_category_id,
                   j.visa_sponsorship, j.relocation_support
            FROM core.jobs j
            LEFT JOIN core.job_descriptions d ON j.job_id = d.job_id AND j.posting_date = d.posting_date
            LEFT JOIN ref.locations l ON j.location_id = l.location_id
            WHERE (j.education_level_id IS NULL
               OR j.experience_level_id IS NULL
               OR j.remote_work_type_id IS NULL
               OR j.job_category_id IS NULL
               OR j.visa_sponsorship IS NULL
               OR j.relocation_support IS NULL)
        """)

        batch_size = 5000
        batch_updates = []
        processed = 0
        updated_count = 0
        t_start = time.time()

        while True:
            rows = stream_cur.fetchmany(batch_size)
            if not rows:
                break

            for r in rows:
                (jid, pdate, title, loc, desc, cur_edu, cur_exp, cur_rem, cur_cat, cur_visa, cur_reloc) = r
                desc = desc or ""
                title = title or ""

                new_edu = cur_edu or (edu_map.get(map_education_level(desc)) if desc else None)
                new_exp = cur_exp or (exp_map.get(map_experience_level(desc, title)))
                new_rem = cur_rem or (remote_map.get(map_remote_work_type(loc or desc)))
                new_cat = cur_cat or (cat_map.get(map_job_category(title, None)))
                new_visa = cur_visa if cur_visa is not None else map_visa_sponsorship(desc)
                new_reloc = cur_reloc if cur_reloc is not None else map_relocation_support(desc)

                # Check if any new value was found
                if (new_edu != cur_edu or new_exp != cur_exp or new_rem != cur_rem or 
                    new_cat != cur_cat or new_visa != cur_visa or new_reloc != cur_reloc):
                    batch_updates.append((
                        new_edu, new_exp, new_rem, new_cat, new_visa, new_reloc, jid, pdate
                    ))

            processed += len(rows)

            # Flush batch via write_conn
            if batch_updates:
                write_cur.executemany("""
                    UPDATE core.jobs SET
                        education_level_id = %s,
                        experience_level_id = %s,
                        remote_work_type_id = %s,
                        job_category_id = %s,
                        visa_sponsorship = %s,
                        relocation_support = %s
                    WHERE job_id = %s AND posting_date = %s
                """, batch_updates)
                updated_count += len(batch_updates)
                batch_updates.clear()

            elapsed = time.time() - t_start
            rate = processed / elapsed if elapsed > 0 else 0
            print(f"Processed: {processed:,} / {target_count:,} ({processed/target_count*100:.1f}%) | "
                  f"Updated: {updated_count:,} | Rate: {rate:,.0f} rows/s", flush=True)

    read_conn.close()
    write_conn.close()
    print(f"\nBackfill finished! Total processed: {processed:,}, Total updated: {updated_count:,} in {time.time() - t_start:.2f}s", flush=True)

if __name__ == "__main__":
    run_full_backfill()
