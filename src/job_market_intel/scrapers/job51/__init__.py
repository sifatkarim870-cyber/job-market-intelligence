"""51job scraper.

Fetches job listings from 51job (https://www.51job.com), China's largest
job board, validated into typed ``RawJob51Job`` objects.

51job publishes no documented API, but its PC web app is backed by an
unauthenticated JSON endpoint at
``https://cupid.51job.com/pc/open/noauth/search-h5`` (found via the
site's own JS bundles — see ``client.py``'s module docstring for the
full discovery trail, the WAF'd pages deliberately avoided, and the
unused-but-documented signing machinery). One response per page of up
to 100 jobs carries every field the pipeline needs: title, company,
location, salary, posting timestamp, employment type, and the full
description.

Typical usage:

    from job_market_intel.scrapers.job51 import Job51Client, Job51Parser, Job51Settings

    settings = Job51Settings()
    client = Job51Client(settings=settings)
    parser = Job51Parser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import Job51Client
from .config import Job51Settings
from .exceptions import Job51Error, Job51FetchError, Job51ResponseError
from .models import RawJob51Job
from .parser import Job51Parser
from .pipeline import Job51Pipeline, Job51PipelineRunResult

__all__ = [
    "Job51Client",
    "Job51Settings",
    "Job51Error",
    "Job51FetchError",
    "Job51ResponseError",
    "RawJob51Job",
    "Job51Parser",
    "Job51Pipeline",
    "Job51PipelineRunResult",
]
