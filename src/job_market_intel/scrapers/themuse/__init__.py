"""The Muse scraper.

Fetches employer-authored job postings from The Muse's public JSON API
(``https://www.themuse.com/api/public/jobs``) and returns validated, typed
``RawThemuseJob`` objects.

This is the largest source available without an API key: probing on
2026-10-12 reported ``page_count = 20,694`` at 20 records per page, roughly
400,000 postings against a corpus of ~115,000 rows.

Typical usage:

    from job_market_intel.scrapers.themuse import (
        ThemuseClient, ThemuseParser, ThemuseSettings,
    )

    raw_jobs = ThemuseClient().fetch_raw_jobs()
    jobs = ThemuseParser().parse_jobs(raw_jobs)

Note on ordering: the feed is NOT time-ordered. Publication dates across the
first three pages ranged from 2025-01-17 to 2026-10-03, so
``ThemuseParser.drop_stale`` is applied to keep the corpus current.
"""

from .client import ThemuseClient
from .config import ThemuseSettings
from .exceptions import ThemuseError, ThemusePermanentError
from .models import RawThemuseJob
from .parser import ThemuseParser
from .pipeline import ThemusePipeline, ThemusePipelineRunResult

__all__ = [
    "RawThemuseJob",
    "ThemuseClient",
    "ThemuseError",
    "ThemuseParser",
    "ThemusePermanentError",
    "ThemusePipeline",
    "ThemusePipelineRunResult",
    "ThemuseSettings",
]
