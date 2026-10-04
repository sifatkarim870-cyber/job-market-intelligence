"""MyJob.mu scraper.

Fetches job listings from MyJob.mu (https://www.myjob.mu), Mauritius's
job board, validated into typed ``RawMyJobJob`` objects.

MyJob.mu publishes no documented API, but its Nuxt frontend talks to a
plain JSON API at ``app.myjob.mu/api/job-board/jobs`` (list, 20 per page)
with per-job detail at ``/jobs/{id}`` — both unauthenticated, confirmed
live during scoping (2026-10-05). This scraper pages through the list,
merges each job's detail payload (the only place ``description`` lives),
and returns typed objects.

Typical usage:

    from job_market_intel.scrapers.myjob import MyJobClient, MyJobParser, MyJobSettings

    settings = MyJobSettings()
    client = MyJobClient(settings=settings)
    parser = MyJobParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import MyJobClient
from .config import MyJobSettings
from .exceptions import MyJobError, MyJobFetchError, MyJobResponseError
from .models import RawMyJobJob
from .parser import MyJobParser
from .pipeline import MyJobPipeline, MyJobPipelineRunResult

__all__ = [
    "MyJobClient",
    "MyJobSettings",
    "MyJobError",
    "MyJobFetchError",
    "MyJobResponseError",
    "RawMyJobJob",
    "MyJobParser",
    "MyJobPipeline",
    "MyJobPipelineRunResult",
]
