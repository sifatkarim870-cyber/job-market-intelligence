"""USAJOBS -- the United States federal government's official job board.

Why this source exists
----------------------
The corpus is geographically lopsided: 68% Iran, seven countries at 1% or more,
and no United States rows at all from any federal source. USAJOBS is the single
largest US employer by headcount -- roughly 1.5 million civilian positions
across ~700 agencies -- and it publishes through a free, key-authenticated data.gov
API with no proxy, no captcha and no per-agreement registration.

It is also unusually rich for a job board. One search response carries the
employing bureau, department and sub-agency, the pay grade and job series, the
salary band with its pay interval, publication and closing dates, and a
structured location with city, state and coordinates.

What actually reaches the corpus is narrower than what the API returns. The
database has no latitude/longitude column and ``CleanedJob.raw_payload`` is not
persisted by ``JobRepository.save_cleaned_job``, so the coordinates, the pay
grade and the job series are parsed and carried but **discarded at save time**.
They are kept in the payload because they cost nothing to retain and a future
column addition should not require another crawl. Adding those columns properly
would change the shard contract for all 22 sources, so it is a separate change
and not something this scraper can decide on its own. The salary band, dates,
organisation hierarchy and structured city/state all *do* persist.

Why a scraper needs two requests per posting
---------------------------------------------
There is **no position detail endpoint**. ``/api/v2/position/{id}`` and four
other spellings all return 404, and the API's ``PositionFormattedDescription``
is a marker object rather than text. The full posting therefore comes from the
public job page, whose ``page-section`` blocks hold ~30,000 characters against
the JSON-LD teaser's ~400. Both halves are used because their field names share
nothing: the API knows the grade and the coordinates, the page knows the duties.

Rate limit
----------
data.gov meters keys at 500 requests/hour. One search page plus one job page per
result is ~51 requests, so the configured inter-request delay is what keeps a
run inside the hourly budget instead of earning a 403 partway through.

Typical usage::

    from job_market_intel.scrapers.usajobs import USAJobsClient, USAJobsParser

    settings = USAJobsSettings(api_key_file=Path("API_USAJOBS.txt"))
    records, failures = USAJobsClient(settings).fetch_raw_jobs()
    jobs, issues = USAJobsParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.usajobs.client import USAJobsClient
from job_market_intel.scrapers.usajobs.config import USAJobsSettings
from job_market_intel.scrapers.usajobs.exceptions import (
    USAJobsAuthError,
    USAJobsError,
    USAJobsFetchError,
    USAJobsParseError,
    USAJobsResponseError,
)
from job_market_intel.scrapers.usajobs.models import RawUSAJobsJob
from job_market_intel.scrapers.usajobs.parser import USAJobsParser
from job_market_intel.scrapers.usajobs.pipeline import (
    USAJobsPipeline,
    USAJobsPipelineRunResult,
)

__all__ = [
    "RawUSAJobsJob",
    "USAJobsAuthError",
    "USAJobsClient",
    "USAJobsError",
    "USAJobsFetchError",
    "USAJobsParseError",
    "USAJobsParser",
    "USAJobsPipeline",
    "USAJobsPipelineRunResult",
    "USAJobsResponseError",
    "USAJobsSettings",
]
