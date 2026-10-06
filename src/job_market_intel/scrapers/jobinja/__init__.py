"""Jobinja scraper.

Fetches job listings from Jobinja (https://jobinja.ir), Iran's largest
job board, validated into typed ``RawJobinjaJob`` objects.

Jobinja publishes no public JSON API (``/api/v10/*`` is auth-only) and
no sitemaps, so the scraper discovers jobs by paginating the
server-rendered listing (``/jobs?page=N`` — 20 jobs/page, newest-first,
≈16.8k corpus) and fetches each job's detail page, whose full record is
embedded as schema.org JSON-LD ``JobPosting`` (identifier/title/
description/datePosted/employmentType/baseSalary IRT/hiringOrganization/
jobLocation) plus ``<h4>…</h4><div class="tags">`` sections for
location, skills, category, and the visible salary text (the
disclosure truth — "توافقی" withholds even when JSON-LD carries a
number). Content arrives in Persian; non-English titles are translated
by CI before classification, descriptions by the local NLLB batch.

Typical usage:

    from job_market_intel.scrapers.jobinja import JobinjaClient, JobinjaParser, JobinjaSettings

    settings = JobinjaSettings()
    client = JobinjaClient(settings=settings)
    parser = JobinjaParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import JobinjaClient
from .config import JobinjaSettings
from .exceptions import JobinjaError, JobinjaFetchError, JobinjaResponseError
from .models import RawJobinjaJob
from .parser import JobinjaParser
from .pipeline import JobinjaPipeline, JobinjaPipelineRunResult

__all__ = [
    "JobinjaClient",
    "JobinjaSettings",
    "JobinjaError",
    "JobinjaFetchError",
    "JobinjaResponseError",
    "RawJobinjaJob",
    "JobinjaParser",
    "JobinjaPipeline",
    "JobinjaPipelineRunResult",
]
