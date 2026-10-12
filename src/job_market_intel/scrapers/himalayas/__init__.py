"""Himalayas scraper.

Fetches job postings from Himalayas' public JSON API
(``https://himalayas.app/jobs/api``) and returns validated, typed
``RawHimalayasJob`` objects.

Himalayas is a remote-job aggregator spanning many employers rather than one
country's job board. It reports salary bounds, a salary period, seniority and
categories -- fields most free boards omit -- and needs no API key.

Typical usage:

    from job_market_intel.scrapers.himalayas import (
        HimalayasClient, HimalayasParser, HimalayasSettings,
    )

    raw_jobs = HimalayasClient().fetch_raw_jobs()
    jobs = HimalayasParser().parse_jobs(raw_jobs)

Note on identity: the list payload carries no numeric id, only ``guid`` -- the
canonical job URL. That is used as ``source_job_id`` because it is stable for
the life of the posting, which is what the natural key
``(source_id, source_job_id, posting_date)`` requires.

Note on pagination: the feed is OFFSET-based. Passing ``page`` is silently
ignored and returns the same window, which is why the client walks offsets.
"""

from .client import HimalayasClient, HimalayasPermanentError
from .config import HimalayasSettings
from .exceptions import HimalayasError
from .models import RawHimalayasJob
from .parser import HimalayasParser
from .pipeline import HimalayasPipeline, HimalayasPipelineRunResult

__all__ = [
    "HimalayasClient",
    "HimalayasError",
    "HimalayasParser",
    "HimalayasPermanentError",
    "HimalayasPipeline",
    "HimalayasPipelineRunResult",
    "HimalayasSettings",
    "RawHimalayasJob",
]
