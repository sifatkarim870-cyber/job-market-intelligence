"""National Employment Agency (nea.gov.kh) -- Cambodia's state jobs portal.

Why this source exists
----------------------
The National Employment Agency is Cambodia's state employment service (under
the Ministry of Labour). Its vacancy board carries employer postings from
across the country, in Khmer, and is a distinct inventory from the existing
``camhr_com`` and ``bongthom_com`` sources. It needs no key, no login, no
proxy and no browser automation.

How it is read
--------------
* Discovery: a POST of the board's own search form to
  ``/vacancy/dtlSearch.do`` (``condDiv=SEARCH``, ``condText=""``,
  ``currentPageNo=N``). Ten rows per page, each navigating via
  ``fnVacancyViewNew('<32 hex>')``. The board reported 654 vacancies on
  2026-11-22 (~66 pages); this scraper reads the first six pages per run.
* Detail: ``/vacancy/view.do?condSeq=<32 hex>`` is server-rendered and
  carries the title (``#vacancyTitle``), employer (``.tit_box span.tit``), a
  summary block of label/value pairs, and labelled sections for the
  recruitment window, employment type, salary, education, experience and
  description.
* Salaries are USD per month; the recruitment window supplies the posting
  and closing dates.

Transport
---------
The bare root ``/`` answers a Cloudflare JS-challenge shell to a non-browser
client, but the content paths this scraper reads do not. Every call goes
through ``curl_cffi`` with ``impersonate="chrome"`` and the bare root is
never requested.

Compliance
----------
``www.nea.gov.kh/robots.txt`` (HTTP 200) is the Cloudflare-managed generic
``User-agent: *`` group with ``Allow: /``. The later groups that disallow
training crawlers do not name this scraper's ordinary browser User-Agent, and
none of them restricts ``/vacancy/``. TLS verification stays on -- no
``verify=False`` anywhere.

Typical usage::

    from job_market_intel.scrapers.nea_gov_kh import NeaGovKhClient, NeaGovKhParser

    records, failures = NeaGovKhClient().fetch_raw_jobs()
    jobs, issues = NeaGovKhParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.nea_gov_kh.client import NeaGovKhClient
from job_market_intel.scrapers.nea_gov_kh.config import NeaGovKhSettings
from job_market_intel.scrapers.nea_gov_kh.exceptions import (
    NeaGovKhError,
    NeaGovKhFetchError,
    NeaGovKhParseError,
    NeaGovKhResponseError,
)
from job_market_intel.scrapers.nea_gov_kh.models import RawNeaGovKhJob
from job_market_intel.scrapers.nea_gov_kh.parser import NeaGovKhParser, parse_detail
from job_market_intel.scrapers.nea_gov_kh.pipeline import (
    NeaGovKhPipeline,
    NeaGovKhPipelineRunResult,
)

__all__ = [
    "NeaGovKhClient",
    "NeaGovKhError",
    "NeaGovKhFetchError",
    "NeaGovKhParseError",
    "NeaGovKhParser",
    "NeaGovKhPipeline",
    "NeaGovKhPipelineRunResult",
    "NeaGovKhResponseError",
    "NeaGovKhSettings",
    "RawNeaGovKhJob",
    "parse_detail",
]
