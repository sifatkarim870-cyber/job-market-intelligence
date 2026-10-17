"""PhilJobNet (philjobnet.gov.ph) -- a Philippine government job board.

Why this source exists
----------------------
The Philippines had **no** postings in the corpus. PhilJobNet is the Philippine
government's official job board: no key, no registration, no proxy, and it
paginates (well, it lists ~10 per page but the pager returns 0 new, so all
postings are on one page).

No structured data
------------------
No schema.org JSON-LD. Everything is markup extraction from a
``.portfolio-details`` block::

    BUILDING ADMINISTRATOR
    Salary not specified
    1PRIME RETAIL CORPORATION
    Apply now
    DUMAGUETE CITY (CAPITAL), NEGROS ORIENTAL
    COLLEGE GRADUATE
    Permanent
    Job Description
    Posted on 17 October 2026
    <description>

or, when a salary is stated::

    BUSINESS DEVELOPMENT OFFICER
    ₱20,000.00
    I PROCESS LIAISON AND CONSULTANCY OPC
    Apply now
    BACUNGAN (LEON T. POSTIGO), ZAMBOANGA DEL NORTE
    ELEMENTARY GRADUATE
    Project-based
    Job Description
    Posted on 17 October 2026
    <description>

The salary trap
---------------
``Salary`` reads ``"not specified"`` on most postings and a single figure
(``\"₱20,000.00\"``) on some. The figure has no stated period, so it is stored
with ``pay_period = monthly`` (the Philippine convention) and that guess is
recorded in ``raw_payload[\"salary_period_assumed\"]`` so it is auditable rather
than silent.

The meta-tag trap
-----------------
``og:title`` / ``og:description`` are **site-wide** (\"PhilJobNet | Job Details\")
and must not be used. The title comes from ``<h1>``.

Compliance
----------
robots.txt returns HTTP 404 -- there is no robots file at all, so nothing is
disallowed.

Typical usage::

    from job_market_intel.scrapers.philjobnet import PhilJobNetClient, PhilJobNetParser

    records, failures = PhilJobNetClient().fetch_raw_jobs()
    jobs, issues = PhilJobNetParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.philjobnet.client import PhilJobNetClient
from job_market_intel.scrapers.philjobnet.config import PhilJobNetSettings
from job_market_intel.scrapers.philjobnet.exceptions import (
    PhilJobNetError,
    PhilJobNetFetchError,
    PhilJobNetParseError,
    PhilJobNetResponseError,
)
from job_market_intel.scrapers.philjobnet.models import RawPhilJobNetJob
from job_market_intel.scrapers.philjobnet.parser import PhilJobNetParser, parse_detail
from job_market_intel.scrapers.philjobnet.pipeline import (
    PhilJobNetPipeline,
    PhilJobNetPipelineRunResult,
)

__all__ = [
    "PhilJobNetCleaner",
    "PhilJobNetClient",
    "PhilJobNetError",
    "PhilJobNetFetchError",
    "PhilJobNetParseError",
    "PhilJobNetParser",
    "PhilJobNetPipeline",
    "PhilJobNetPipelineRunResult",
    "PhilJobNetResponseError",
    "PhilJobNetSettings",
    "RawPhilJobNetJob",
    "parse_detail",
]
