import psycopg

conn = psycopg.connect("postgresql://app_user:changeme@localhost:5432/job_market_intelligence")
cur = conn.cursor()

# Get total count of jobs
cur.execute("SELECT count(*) FROM core.jobs")
total_jobs = cur.fetchone()[0]
print(f"Total jobs in core.jobs: {total_jobs}")

# Get all columns in core.jobs
cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_schema = 'core' AND table_name = 'jobs'
    ORDER BY ordinal_position
""")
cols = cur.fetchall()

print(f"\nAudit of all {len(cols)} columns in core.jobs:")
print(f"{'Column Name':35s} | {'Data Type':18s} | {'Non-null Count':15s} | {'Non-null %':10s}")
print("-" * 85)

for col_name, data_type in cols:
    cur.execute(f"SELECT count({col_name}) FROM core.jobs WHERE {col_name} IS NOT NULL")
    non_null = cur.fetchone()[0]
    pct = (non_null / total_jobs) * 100 if total_jobs > 0 else 0
    print(f"{col_name:35s} | {data_type:18s} | {non_null:15,d} | {pct:8.2f}%")

conn.close()
