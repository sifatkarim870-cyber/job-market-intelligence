"""TopJobs (topjobs.lk) -- a Sri Lankan job board.

Why this source exists
----------------------
Sri Lanka had one source (``ikman_lk``, 750 rows) and **no country row**: all
750 of its postings carried a NULL country, because ``ref.countries`` had no
``LK``. TopJobs is the country's long-running classifieds board, needs no key,
no registration and no proxy, and held **4,583 open postings** on 2026-11-20 --
an order of magnitude more than the corpus had for the country.

Traps, each measured 2026-11-20
-------------------------------
1. **The rows are not links.** Each ``<tr>`` opens a popup through
   ``onclick="createAlert('rid','ac','jc','ec','id')"``; the detail URL is
   built from those four codes. An anchor-based parser finds nothing.
2. **The listing carries fields the ad page does not** -- opening date,
   closing date and town -- and the ad page carries fields the listing does
   not (the ``ad-status`` labels). Both are read; neither is a superset.
3. **Two date formats**: the listing writes ``Fri Nov 20 2026``, the detail
   page writes ``03/12/2026`` (day-first).
4. **The title's trailing parenthetical is headcount** ("Sales
   Representative  (10)"), not part of the title -- the ad page confirms it.
5. **Most ads are images**: 71 of 75 sampled had an ``<img>`` and no body
   text. They are still stored, with ``description_clean=None`` and
   ``raw_payload['description_is_image']=True``.
6. **No salary field** anywhere in the markup; one sampled body mentioned pay
   at all. ``currency_iso_code``/``pay_period`` state the home market
   (``LKR``/``monthly``), not an amount.
7. **No country or city in the markup** -- only a town column. The cleaner
   falls back to "Sri Lanka" and ``SOURCE_HOME_COUNTRY`` pins the country.

Compliance
----------
robots.txt (HTTP 200) allows both the listing and ``/employer/`` paths; no
key, no login, no proxy, and detail pages are fetched at a fixed delay.

Typical usage::

    from job_market_intel.scrapers.topjobs_lk import TopJobsLkClient, TopJobsLkParser

    records, failures = TopJobsLkClient().fetch_raw_jobs()
    jobs, issues = TopJobsLkParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.topjobs_lk.client import TopJobsLkClient
from job_market_intel.scrapers.topjobs_lk.config import TopJobsLkSettings
from job_market_intel.scrapers.topjobs_lk.exceptions import (
    TopJobsLkError,
    TopJobsLkFetchError,
    TopJobsLkParseError,
    TopJobsLkResponseError,
)
from job_market_intel.scrapers.topjobs_lk.models import RawTopJobsLkJob
from job_market_intel.scrapers.topjobs_lk.parser import (
    TopJobsLkParser,
    detail_url,
    parse_detail,
    parse_detail_date,
    parse_listing,
    parse_listing_date,
    split_headcount,
)
from job_market_intel.scrapers.topjobs_lk.pipeline import (
    TopJobsLkPipeline,
    TopJobsLkPipelineRunResult,
)

__all__ = [
    "RawTopJobsLkJob",
    "TopJobsLkClient",
    "TopJobsLkError",
    "TopJobsLkFetchError",
    "TopJobsLkParseError",
    "TopJobsLkParser",
    "TopJobsLkPipeline",
    "TopJobsLkPipelineRunResult",
    "TopJobsLkResponseError",
    "TopJobsLkSettings",
    "detail_url",
    "parse_detail",
    "parse_detail_date",
    "parse_listing",
    "parse_listing_date",
    "split_headcount",
]
