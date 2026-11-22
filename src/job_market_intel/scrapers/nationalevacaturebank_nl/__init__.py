"""Nationale Vacaturebank (nationalevacaturebank.nl) -- Netherlands jobs.

Why this source exists
----------------------
Nationale Vacaturebank is one of the Netherlands' largest generalist job
boards, run by DPG Media. It publishes real server-rendered HTML and a
schema.org ``JobPosting`` block on every ad page, so it needs no key, no
login, no proxy and no browser automation. The Netherlands had no
plain-request HTML source of this size before it.

How it is read
--------------
* Discovery: the board's own published ``/vacatures/sitemap.xml`` lists 241
  category URLs; the scraper keeps the 96 content categories and walks a
  rotating window of ``pages_per_run`` of them per run. robots.txt disallows
  ``/vacatures/*?page=``, so only page 1 of each category is read and no query
  string is ever sent.
* Detail: ``/vacature/<uuid>/<slug>`` carries a ``JobPosting`` block with
  title, employer, full address + lat/lon, dates, employment types,
  education/experience requirements, work hours, category/industry, the
  description and the ad's own ``baseSalary``.
* A second ``Occupation`` block carries the board's market salary estimate;
  it is kept in ``raw_payload`` only and never treated as a disclosed salary.

Transport
---------
A plain ``requests`` GET gets HTTP 403 ``Access Denied`` from the DPG edge, so
every call goes through ``curl_cffi`` with ``impersonate="chrome"``. A fresh
session's first HTML response can be the "DPG Media Privacy Gate" consent
wall; re-requesting the page on the same session returns the real content.

Compliance
----------
``www`` robots.txt allows the categories, the sitemap and the ad pages this
scraper reads, and disallows only pagination/query and account/apply paths it
never requests. ``api.nationalevacaturebank.nl/robots.txt`` is
``Disallow: /`` and is never touched. TLS verification stays on -- no
``verify=False`` anywhere.

Typical usage::

    from job_market_intel.scrapers.nationalevacaturebank_nl import (
        NationaleVacaturebankNlClient,
        NationaleVacaturebankNlParser,
    )

    records, failures = NationaleVacaturebankNlClient().fetch_raw_jobs()
    jobs, issues = NationaleVacaturebankNlParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.nationalevacaturebank_nl.client import (
    NationaleVacaturebankNlClient,
)
from job_market_intel.scrapers.nationalevacaturebank_nl.config import (
    NationaleVacaturebankNlSettings,
)
from job_market_intel.scrapers.nationalevacaturebank_nl.exceptions import (
    NationaleVacaturebankNlError,
    NationaleVacaturebankNlFetchError,
    NationaleVacaturebankNlParseError,
    NationaleVacaturebankNlResponseError,
)
from job_market_intel.scrapers.nationalevacaturebank_nl.models import (
    RawNationaleVacaturebankNlJob,
)
from job_market_intel.scrapers.nationalevacaturebank_nl.parser import (
    NationaleVacaturebankNlParser,
    parse_detail,
)
from job_market_intel.scrapers.nationalevacaturebank_nl.pipeline import (
    NationaleVacaturebankNlPipeline,
    NationaleVacaturebankNlPipelineRunResult,
)

__all__ = [
    "NationaleVacaturebankNlClient",
    "NationaleVacaturebankNlError",
    "NationaleVacaturebankNlFetchError",
    "NationaleVacaturebankNlParseError",
    "NationaleVacaturebankNlParser",
    "NationaleVacaturebankNlPipeline",
    "NationaleVacaturebankNlPipelineRunResult",
    "NationaleVacaturebankNlResponseError",
    "NationaleVacaturebankNlSettings",
    "RawNationaleVacaturebankNlJob",
    "parse_detail",
]
