"""Job.am scraper.

Fetches job listings from Job.am (https://job.am), Armenia's job board,
validated into typed ``RawJobAmJob`` objects.

Job.am publishes no documented API, but its board is fully served by a
plain JSON endpoint at ``https://job.am/api/jobs`` that returns the
entire listing (~1,136 jobs) in one unauthenticated GET (confirmed live
during scoping, 2026-10-05). The list payload has no posting date,
description, or employment type — those live in each job page's
schema.org ``JobPosting`` JSON-LD, which the client fetches per job
(with a politeness delay) and nests under ``_detail``.

Typical usage:

    from job_market_intel.scrapers.jobam import JobAmClient, JobAmParser, JobAmSettings

    settings = JobAmSettings()
    client = JobAmClient(settings=settings)
    parser = JobAmParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import JobAmClient
from .config import JobAmSettings
from .exceptions import JobAmError, JobAmFetchError, JobAmResponseError
from .models import RawJobAmJob
from .parser import JobAmParser
from .pipeline import JobAmPipeline, JobAmPipelineRunResult

__all__ = [
    "JobAmClient",
    "JobAmSettings",
    "JobAmError",
    "JobAmFetchError",
    "JobAmResponseError",
    "RawJobAmJob",
    "JobAmParser",
    "JobAmPipeline",
    "JobAmPipelineRunResult",
]
