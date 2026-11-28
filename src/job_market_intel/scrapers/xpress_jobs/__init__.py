"""XpressJobs (xpress.jobs) scraper.

Fetches job listings from XpressJobs, Sri Lanka's general job board, by
walking its own keyless public JSON API and hydrating each row from the
public detail endpoint, validated into typed ``RawXpressJob`` objects.

Discovery and data are two keyless GETs, both confirmed live during
scoping (2026-11-28):

* **Listing** - ``GET https://xpress.jobs/api/jobs/searchJobs`` answers a
  bare JSON array of listing rows with ``page`` (1-based), ``pageSize``
  (capped at 100) and ``sortBy=SortedCreateDate DESC`` (deterministic,
  newest-first; the default ``NEWID()`` is random).
* **Detail** - ``GET
  https://xpress.jobs/api/jobs/publishedJob?jobId=<id>`` returns the full
  record: the HTML ``jobInfo`` body, salary strings, ``sectors``, the
  nested ``jobItem`` and the ``organization`` block.

The public page URL is ``https://xpress.jobs/jobs/view/<jobId>`` (HTTP 200).

``https://xpress.jobs/robots.txt`` (HTTP 200, 114 bytes) is a single
``User-agent: *`` group with an **empty** ``Disallow:`` -- everything is
allowed -- plus a ``Sitemap:`` line and no ``Crawl-delay``. No key, no
registration, no proxy, no browser.

Typical usage:

    from job_market_intel.scrapers.xpress_jobs import (
        XpressJobsClient, XpressJobsParser, XpressJobsSettings,
    )

    settings = XpressJobsSettings()
    client = XpressJobsClient(settings=settings)
    parser = XpressJobsParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import XpressJobsClient
from .config import XpressJobsSettings
from .exceptions import (
    XpressJobsError,
    XpressJobsFetchError,
    XpressJobsResponseError,
)
from .models import RawXpressJob
from .parser import XpressJobsParser
from .pipeline import XpressJobsPipeline, XpressJobsPipelineRunResult

__all__ = [
    "XpressJobsClient",
    "XpressJobsSettings",
    "XpressJobsError",
    "XpressJobsFetchError",
    "XpressJobsResponseError",
    "RawXpressJob",
    "XpressJobsParser",
    "XpressJobsPipeline",
    "XpressJobsPipelineRunResult",
]
