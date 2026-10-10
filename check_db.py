import os
from job_market_intel.db.session import get_session
from sqlalchemy import text

db_url = os.environ.get('DATABASE_URL', 'NOT SET')
host = db_url.split('@')[-1] if '@' in db_url else db_url
print('DATABASE_URL host:', host)

with get_session() as session:
    jobs = session.execute(text('SELECT count(*) FROM core.jobs')).scalar()
    companies = session.execute(text('SELECT count(*) FROM core.companies')).scalar()
    ixdf = session.execute(text('SELECT company_id, company_name FROM core.companies WHERE company_id IN (250, 403)')).all()
    print('jobs:', jobs, ' companies:', companies)
    print('IxDF rows via get_session():', ixdf)
