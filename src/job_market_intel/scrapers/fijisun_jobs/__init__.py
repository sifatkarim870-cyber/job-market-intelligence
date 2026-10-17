"""Fiji Sun jobs (fijisun.com.fj) -- a Fijian job board.

Why this source exists
----------------------
Fiji had **no** postings in the corpus. Fiji Sun is a Fijian news publisher's
job board: no key, no registration, no proxy, and it paginates via
``/jobs/browse`` (2 new postings per page).

No structured data, and a meta-tag trap
---------------------------------------
No schema.org JSON-LD. And **``og:title`` / ``og:description`` are SITE-wide** --
"Fiji Sun - Your Trusted Source for Fiji News" -- so a parser trusting meta tags
would store the site's name as every job's title. The title comes from ``<h1>``,
and the company from the ``<h1>``'s parent text minus the ``<h1>``.

Discovery
---------
``/jobs`` carries 8 postings, ``/jobs/browse`` returns 2 new, and ``/jobs/page/2``
and ``/jobs?page=2`` both return 0. Hrefs are **relative** (measured 8 relative,
0 absolute).

The Job overview block
----------------------
The ``.border.border-neutral-300`` / ``aside.sticky`` block carries labelled rows:

    Posted 1 week ago
    Salary T.B.D.
    Openings 1 position
    Experience 1+ yrs exp.
    Type Full-time
    Location Lautoka
    Closes 5 November 2026

The posting date is **relative** ("Posted 1 week ago", "Posted 3 days ago") and
is converted to a calendar date, so ``raw_payload["posted_date_is_derived"]`` is
``True`` and any freshness analysis over this source must treat the date as an
estimate. The closing date is **absolute** ("Closes 5 November 2026").

Salary reads ``"T.B.D."`` on every measured posting -- not a figure -- so no
salary is stored. The verbatim string is kept in ``raw_payload["salary_text"]``.

Compliance
----------
robots.txt: ``User-agent: *`` allows ``/`` and disallows ``/api/``, ``/admin``
and ``/todays-paper/``. Job pages are permitted.

Typical usage::

    from job_market_intel.scrapers.fijisun_jobs import FijiSunJobsClient, FijiSunJobsParser

    records, failures = FijiSunJobsClient().fetch_raw_jobs()
    jobs, issues = FijiSunJobsParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.fijisun_jobs.client import FijiSunJobsClient
from job_market_intel.scrapers.fijisun_jobs.config import FijiSunJobsSettings
from job_market_intel.scrapers.fijisun_jobs.exceptions import (
    FijiSunJobsError,
    FijiSunJobsFetchError,
    FijiSunJobsParseError,
    FijiSunJobsResponseError,
)
from job_market_intel.scrapers.fijisun_jobs.models import RawFijiSunJobsJob
from job_market_intel.scrapers.fijisun_jobs.parser import FijiSunJobsParser, parse_detail
from job_market_intel.scrapers.fijisun_jobs.pipeline import (
    FijiSunJobsPipeline,
    FijiSunJobsPipelineRunResult,
)

__all__ = [
    "FijiSunJobsCleaner",
    "FijiSunJobsClient",
    "FijiSunJobsError",
    "FijiSunJobsFetchError",
    "FijiSunJobsParseError",
    "FijiSunJobsParser",
    "FijiSunJobsPipeline",
    "FijiSunJobsPipelineRunResult",
    "FijiSunJobsResponseError",
    "FijiSunJobsSettings",
    "RawFijiSunJobsJob",
    "parse_detail",
]
