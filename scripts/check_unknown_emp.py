import psycopg

conn = psycopg.connect('postgresql://app_user:changeme@localhost:5432/job_market_intelligence')
cur = conn.cursor()
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'core' AND table_name = 'companies'")
print("Columns:", [r[0] for r in cur.fetchall()])
