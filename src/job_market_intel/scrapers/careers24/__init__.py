"""Careers24 (careers24.com) -- the South African job board.

Why this source exists
----------------------
South Africa had **zero** postings in the corpus. The previously-built sources
cover Iran (jobinja, jobvision, irantalent), Israel (jobmaster), Armenia
(staff.am territory), Mauritius (myjob), Georgia, Canada, the US and a set of
remote-first aggregators -- but nothing in sub-Saharan Africa. Careers24 is
one of the largest general boards in the region and needs no API key, no
registration and no proxy, which puts it in the buildable set while LinkedIn,
Monster, Jooble and CareerJet are not.

It is also structurally interesting as a **third** schema.org variant in this
project. Two already exist and both are different from each other:

* **Wellfound** -- ``identifier`` is a ``PropertyValue``, salary is a
  ``minValue``/``maxValue`` range, JSON-LD is top-level.
* **Built In** -- ``identifier`` is a ``PropertyValue``, salary is a
  ``minValue``/``maxValue`` range, and the ``JobPosting`` is nested inside an
  ``@graph`` document rather than at the top level.
* **Careers24** -- ``identifier`` is a ``PropertyValue`` (same as both), the
  JSON-LD is top-level (same as Wellfound), and the salary figure sits **one
  level deeper than in either of them**, with no band at all::

      {"currency": "ZAR",
       "value": {"@type": "QuantitativeValue", "value": "180", "unitText": "DAY"}}

That last point is the trap, and this scraper fell into it. The first
implementation handled the band shape only; because ``baseSalary`` is optional
the batch still validated at 40/40 parsed while recording a salary for **0 of
the 40 postings, 15 of which publish one**. Nothing errored and nothing was
logged -- the coverage simply read zero.
:func:`~job_market_intel.scrapers.careers24.parser._extract_salary` now accepts
all three shapes and records which one it saw in ``raw_payload`` as
``salary_shape``, so a future change in the site's markup shows up as a
salary-coverage number rather than as nothing at all.

The other trap is one of parsing, not of data
----------------------------------------------
Detail hrefs carry a rank query string -- ``/jobs/adverts/2393633-production-manager-/?jobindex=3``
-- so a regex anchored on the closing quote after the slug matches **zero**
adverts on a board that is plainly serving them. This is why Careers24 briefly
looked like an empty board during triage. The client's pattern tolerates a
trailing ``?...`` and the tests pin that case specifically.

Measured on 8 postings, 2026-10-15: 12 of 12 JSON-LD fields present on all 8
(``title``, ``description``, ``industry``, ``identifier``, ``datePosted``,
``validThrough``, ``employmentType``, ``hiringOrganization``, ``jobLocation``),
with ``baseSalary`` on 2 of 8. Descriptions run 217-627 characters -- short
relative to Wellfound or Built In, but real. The listing page yields 10 adverts
and paginates for real: 54 distinct ids across 6 pages, changing every page.

A wider run on 2026-10-16 over 40 postings found ``baseSalary`` on 15 of 40
(37%): yearly 10, monthly 3, daily 1, and one with an empty ``unitText`` that
the cleaner drops rather than defaulting to yearly -- ``R 80`` is plainly not an
annual figure.

One caveat the board does not advertise: Careers24 is South African but not
South Africa-only. One of the first 40 postings is a Durban-based "USA
Collections Advisor", and one carries ``addressCountry: "Uganda"``, which the
resolver maps onto ZA because that country is not in ``ref.countries``. The
home-country fallback is doing its job, but it is a fallback, not a fact.

Compliance
----------
robots.txt is real ``text/plain`` (646 bytes) listing ~16 named user-agent
groups (Scrapy, Yandex, Baiduspider, SemrushBot, PetalBot, ...), several of
which carry ``Disallow: /``. **There is no ``User-agent: *`` group.** Under RFC
9309 that leaves this crawler subject to no rule in the file, and
``urllib.robotparser`` agrees, reporting ``/jobs`` and ``/jobs/adverts/...`` as
fetchable. That is worth stating explicitly rather than inferring, because the
naive reading -- "no ``*`` group, therefore assume blocked" -- would discard
the source, and because it is the only board here where permission comes from
the group's *absence* rather than from a permissive rule.

Requests are sent at 1.2s intervals with an identifying User-Agent.

Typical usage::

    from job_market_intel.scrapers.careers24 import Careers24Client, Careers24Parser

    records, failures = Careers24Client().fetch_raw_jobs()
    jobs, issues = Careers24Parser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.careers24.client import Careers24Client
from job_market_intel.scrapers.careers24.config import Careers24Settings
from job_market_intel.scrapers.careers24.exceptions import (
    Careers24Error,
    Careers24FetchError,
    Careers24ParseError,
    Careers24ResponseError,
)
from job_market_intel.scrapers.careers24.models import RawCareers24Job
from job_market_intel.scrapers.careers24.parser import Careers24Parser
from job_market_intel.scrapers.careers24.pipeline import (
    Careers24Pipeline,
    Careers24PipelineRunResult,
)

__all__ = [
    "Careers24Client",
    "Careers24Error",
    "Careers24FetchError",
    "Careers24ParseError",
    "Careers24Parser",
    "Careers24Pipeline",
    "Careers24PipelineRunResult",
    "Careers24ResponseError",
    "Careers24Settings",
    "RawCareers24Job",
]
