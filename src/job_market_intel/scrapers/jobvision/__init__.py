"""Jobvision scraper.

Fetches job listings from Jobvision (https://jobvision.ir — "جاب ویژن",
an Iranian job platform), validated into typed ``RawJobvisionJob``
objects.

Discovery walks the public ``/sitemap/jobposts.xml`` (~60k job URLs with
Persian slugs; *not* newest-first, so the pipeline feeds the repository's
known-id set to the client as a skip-known exclusion) and each record is
fetched from the unauthenticated ``JobPost/Detail`` JSON API (the same
data the site's own SSR page embeds: title, HTML description, salary in
millions of Toman or null, workType, activation/expire dates, location,
categories, company). Content is Persian; titles are translated by CI
before classification, descriptions by the local NLLB batch.

Typical usage:

    from job_market_intel.scrapers.jobvision import (
        JobvisionClient, JobvisionParser, JobvisionSettings,
    )

    settings = JobvisionSettings()
    client = JobvisionClient(settings=settings)
    parser = JobvisionParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import JobvisionClient
from .config import JobvisionSettings
from .exceptions import JobvisionError, JobvisionFetchError, JobvisionResponseError
from .models import RawJobvisionJob
from .parser import JobvisionParser
from .pipeline import JobvisionPipeline, JobvisionPipelineRunResult

__all__ = [
    "JobvisionClient",
    "JobvisionSettings",
    "JobvisionError",
    "JobvisionFetchError",
    "JobvisionResponseError",
    "RawJobvisionJob",
    "JobvisionParser",
    "JobvisionPipeline",
    "JobvisionPipelineRunResult",
]
