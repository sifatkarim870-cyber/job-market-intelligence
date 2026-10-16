"""CareerJunction (careerjunction.co.za) -- a South African job board.

Why this source exists
----------------------
South Africa had 40 postings from careers24. CareerJunction is the country's
second-largest board and needs no API key, no registration and no proxy. It
adds 25 more postings from a different employer base.

The one thing worth knowing before writing any of this
------------------------------------------------------
CareerJunction publishes a schema.org ``JobPosting`` in a ``<script
type="application/ld+json">`` block on each detail page, and the JSON is
**malformed**: the ``description`` string contains raw newlines and HTML
entities, which makes ``json.loads`` raise ``Invalid control character``. A
strict parser reads nothing at all from every page -- which is exactly what
the first probe reported, before the fix was found. The fix is
``json.loads(block, strict=False)``, which tolerates control characters inside
strings. Every field extracts cleanly that way.

Discovery is **single-page**: ``/jobs`` returns 25 posting links and ``?page=2``
returns the same 25, so the pager is ignored.

The payload
-----------
Measured over 1 posting on 2026-10-17:

* 12 of 12 fields on the posting -- ``title``, ``url``, ``datePosted``,
  ``validThrough``, ``description``, ``industry``, ``employmentType``,
  ``baseSalary``, ``hiringOrganization`` (name + url), ``jobLocation`` (address
  with locality + country, geo with lat/lon);
* ``addressCountry: "ZA"``, an ISO code;
* descriptions of 3400+ characters, in English, ``<span>``/``<p>``-wrapped with
  entities;
* ``employmentType: "Default"``, which is not a standard schema.org value;
* ``baseSalary`` value ``"R Undisclosed"``, which is not a salary.

Two absences are facts about the board rather than parser gaps, and both shape
the design:

* **No ``identifier`` (0 of 1).** Nothing in the payload names the posting, so
  the URL id is the key. That is also what makes re-runs idempotent.
* **No real ``baseSalary`` (0 of 1).** CareerJunction publishes no salary, so
  every row has ``salary_disclosed = False`` and no ``pay_period`` is claimed
  about a figure that does not exist. This is one of two sources in the corpus
  where that is true (the other is Net-Empregos), and the coverage number should
  be read as a fact about South African job postings, not as a scraper
  limitation.

``datePosted`` / ``validThrough`` are formatted ``"2026/10/16 10:33:33 AM"``
-- not ISO 8601. A custom date parser handles this.

Compliance
----------
robots.txt is real ``text/plain``, 128 bytes. The governing ``User-agent: *``
group is ``Allow: /``, disallowing only ``/myprofile/applied-jobs`` and
``/myprofile/EditProfile``. ``/jobs`` and ``/<slug>-job-<id>.aspx`` are
permitted.

Requests are sent at 1.0s intervals with an identifying User-Agent. Detail
pages are 80-90 KB, among the largest served in this project, so the page cap
is the request-budget knob.

Typical usage::

    from job_market_intel.scrapers.careerjunction import CareerJunctionClient, CareerJunctionParser

    records, failures = CareerJunctionClient().fetch_raw_jobs()
    jobs, issues = CareerJunctionParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.careerjunction.client import CareerJunctionClient
from job_market_intel.scrapers.careerjunction.config import CareerJunctionSettings
from job_market_intel.scrapers.careerjunction.exceptions import (
    CareerJunctionError,
    CareerJunctionFetchError,
    CareerJunctionParseError,
    CareerJunctionResponseError,
)
from job_market_intel.scrapers.careerjunction.models import RawCareerJunctionJob
from job_market_intel.scrapers.careerjunction.parser import CareerJunctionParser
from job_market_intel.scrapers.careerjunction.pipeline import (
    CareerJunctionPipeline,
    CareerJunctionPipelineRunResult,
)

__all__ = [
    "CareerJunctionClient",
    "CareerJunctionError",
    "CareerJunctionFetchError",
    "CareerJunctionParseError",
    "CareerJunctionParser",
    "CareerJunctionPipeline",
    "CareerJunctionPipelineRunResult",
    "CareerJunctionResponseError",
    "CareerJunctionSettings",
    "RawCareerJunctionJob",
]
