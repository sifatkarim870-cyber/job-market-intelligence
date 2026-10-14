"""Wellfound -- the startup and tech job board (formerly angel.co).

Why this source exists
----------------------
The corpus had no startup/VC-backed-company segment at all, and its
geographic spread was 68% Iran across only seven countries with 1% or more.
Wellfound is US/UK/DE/FR-heavy, remote-friendly, and unusually rich per
posting: 14 of 14 JSON-LD fields present on every posting measured on
2026-10-14, including an explicit salary band with currency and period, the
employer's website and logo, and per-office coordinates.

It is also the best salary source added so far -- 6 of 6 postings sampled
carried a real ``minValue``/``maxValue``, where most boards carry a figure on
only some rows.

Why discovery only works through ``/location/...``
---------------------------------------------------
``/jobs`` returns HTTP 200, renders a ``page=N`` pager, and then **ignores the
parameter**: pages 1 through 11 each returned the identical 43 job ids and zero
new ones (measured 2026-10-14). ``/location/<country>`` and
``/role/l/<role>/<country>`` both paginate correctly, yielding 45-58 distinct
jobs per page, with 540 distinct US jobs found across 11 pages.

robots.txt is served as ``Content-Type: text/html`` despite being real
plain-text robots content. Its ``User-agent: *`` rules disallow ``/_jobs/``,
``/*?after_sign_in=*`` and ``/*?inFrame=*``. This scraper uses ``/location/``,
``/role/`` and ``/jobs/<id>-<slug>``; ``/jobs/`` is a different path from the
disallowed ``/_jobs/``.

Typical usage::

    from job_market_intel.scrapers.wellfound import WellfoundClient, WellfoundParser

    records, failures = WellfoundClient().fetch_raw_jobs()
    jobs, issues = WellfoundParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.wellfound.client import WellfoundClient
from job_market_intel.scrapers.wellfound.config import WellfoundSettings
from job_market_intel.scrapers.wellfound.exceptions import (
    WellfoundError,
    WellfoundFetchError,
    WellfoundParseError,
    WellfoundResponseError,
)
from job_market_intel.scrapers.wellfound.models import RawWellfoundJob
from job_market_intel.scrapers.wellfound.parser import WellfoundParser
from job_market_intel.scrapers.wellfound.pipeline import (
    WellfoundPipeline,
    WellfoundPipelineRunResult,
)

__all__ = [
    "RawWellfoundJob",
    "WellfoundClient",
    "WellfoundError",
    "WellfoundFetchError",
    "WellfoundParseError",
    "WellfoundParser",
    "WellfoundPipeline",
    "WellfoundPipelineRunResult",
    "WellfoundResponseError",
    "WellfoundSettings",
]
