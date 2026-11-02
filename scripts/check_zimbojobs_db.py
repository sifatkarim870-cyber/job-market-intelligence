import psycopg

conn = psycopg.connect('postgresql://app_user:changeme@localhost:5432/job_market_intelligence')
cur = conn.cursor()
cur.execute("""
    SELECT job_id, job_title, education_level_id, experience_level_id, remote_work_type_id, job_category_id 
    FROM core.jobs 
    WHERE source_id = 1435
""")
rows = cur.fetchall()
print(f"Total inserted rows for zimbojobs_com: {len(rows)}")
for r in rows:
    print(f"Job {r[0]}: {r[1][:40]} | edu={r[2]} | exp={r[3]} | remote={r[4]} | cat={r[5]}")
