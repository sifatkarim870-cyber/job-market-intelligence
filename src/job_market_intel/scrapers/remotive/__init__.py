"""Remotive scraper.

Fetches job listings from Remotive's public JSON API
(``https://remotive.com/api/remote-jobs``) and returns validated, typed
``RawRemotiveJob`` objects.

This package deliberately does NOT clean, normalize, or store data — that
is the responsibility of later pipeline steps (data cleaning, database
insertion). Its only job is: fetch reliably, validate what comes back, and
hand back a clean list of typed Python objects.

Typical usage:

    from job_market_intel.scrapers.remotive import RemotiveClient, RemotiveParser, RemotiveSettings

    settings = RemotiveSettings()
    client = RemotiveClient(settings=settings)
    parser = RemotiveParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import RemotiveClient
from .config import RemotiveSettings
from .exceptions import RemotiveError, RemotiveFetchError, RemotiveResponseError
from .models import RawRemotiveJob
from .parser import RemotiveParser
from .pipeline import RemotivePipeline, RemotivePipelineRunResult

__all__ = [
    "RemotiveClient",
    "RemotiveSettings",
    "RemotiveError",
    "RemotiveFetchError",
    "RemotiveResponseError",
    "RawRemotiveJob",
    "RemotiveParser",
    "RemotivePipeline",
    "RemotivePipelineRunResult",
]
