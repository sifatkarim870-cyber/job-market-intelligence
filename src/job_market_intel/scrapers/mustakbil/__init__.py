"""Mustakbil (mustakbil.com) -- a large Pakistani job board.

Why this source exists
----------------------
Pakistan had **no** postings in the corpus. The existing sources cover Iran,
Israel, Armenia, Mauritius, Georgia, Canada, the US, China, South-East Asia,
South Africa, and now India -- but nothing in Pakistan. Mustakbil needs no API
key, no registration and no proxy.

The one thing that makes this board unusual is how it must be crawled
----------------------------------------------------------------
**There is no working pagination.** ``/jobs`` returns 43 posting ids and
``/jobs?page=2`` is *byte-identical* -- 398,957 bytes both times, the same 43
ids, zero new. That is the same trap as Wellfound, and it means a scraper built
the obvious way would fetch one page and call it a day.

Breadth has to come from **category paths** instead: ``/jobs/pakistan/<slug>``.
Of 25 plausible slugs measured on 2026-10-16, **8 return HTTP 200 with job
links and 17 return 404**. Those 8 add 80 ids beyond the baseline, giving **123
distinct postings** across nine paths:

    /jobs                                     43 ids
    /jobs/pakistan/information-technology     20 ids (19 new)
    /jobs/pakistan/engineering                20 ids (18 new)
    /jobs/pakistan/healthcare                  5 ids ( 5 new)
    /jobs/pakistan/sales                      20 ids (11 new)
    /jobs/pakistan/education                  20 ids (18 new)
    /jobs/pakistan/security                    2 ids ( 2 new)
    /jobs/pakistan/pharmacy                    4 ids ( 4 new)
    /jobs/pakistan/finance                     4 ids ( 3 new)

That ratio -- 8 of 25 guesses correct -- is why the list is measured rather than
inferred, and why ``config.py`` holds the working slugs explicitly instead of
generating them.

Rate limiting
-------------
The site throttles **at the connection level**, not with a 429. A burst of
listing fetches succeeds, and then every *detail* fetch fails with
``ConnectionError`` until a multi-minute cool-off. Measured: 3.5s between
requests was not enough; 75s of total quiet restored service. The default
``MUSTAKBIL_INTER_REQUEST_DELAY_SECONDS`` is therefore 4.0, an order of
magnitude above the politest setting used by any other source here, and it is
not negotiable downwards without re-measuring. A run reporting a high
``fetch_failures`` count has this symptom.

The payload
-----------
A schema.org ``JobPosting`` at the top level of the JSON-LD, with:

* descriptions of 2-4k characters, containing real ``<b>``/``<ul>``/``<li>``
  structure -- the same tier as Wellfound and Built In;
* ``baseSalary`` as a band nested under ``value.value``
  (``{"currency": "PKR", "value": {"@type": "QuantitativeValue", "minValue":
  40000, "maxValue": 60000, "unitText": "MONTH"}}``), the same shape Apna uses
  and different from Wellfound's and Built In's;
* a nested ``experienceRequirements`` of type
  ``OccupationalExperienceRequirements`` carrying ``monthsOfExperience`` -- the
  only source here that yields an actual experience figure;
* ``addressCountry: "PK"``, an ISO code rather than a country name;
* ``identifier.value`` as a **string**, where Apna's is a JSON number;
* ``validThrough`` with seven fractional-second digits
  (``2027-01-16T19:00:00.0000000Z``), which ``datetime.fromisoformat`` rejects
  before Python 3.11 -- so the date is read from the leading ``YYYY-MM-DD``;
* **no** ``skills`` field, so ``CleanedJob.skills`` is honestly empty here
  rather than empty because a parser missed something.

Compliance
----------
robots.txt is real ``text/plain``, 1,882 bytes. The governing ``User-agent: *``
group is ``Allow: /``, disallowing only ``/clearCache``, ``/clearcache`` and
``/content/images/ads/`` -- none of which is a job path. The named groups
(SemrushBot, AhrefsBot, PetalBot, DotBot, SeznamBot, ...) mostly carry
``Disallow: /``, which does not apply to this crawler.

Typical usage::

    from job_market_intel.scrapers.mustakbil import MustakbilClient, MustakbilParser

    records, failures = MustakbilClient().fetch_raw_jobs()
    jobs, issues = MustakbilParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.mustakbil.client import MustakbilClient
from job_market_intel.scrapers.mustakbil.config import MustakbilSettings
from job_market_intel.scrapers.mustakbil.exceptions import (
    MustakbilError,
    MustakbilFetchError,
    MustakbilParseError,
    MustakbilResponseError,
)
from job_market_intel.scrapers.mustakbil.models import RawMustakbilJob
from job_market_intel.scrapers.mustakbil.parser import MustakbilParser
from job_market_intel.scrapers.mustakbil.pipeline import (
    MustakbilPipeline,
    MustakbilPipelineRunResult,
)

__all__ = [
    "MustakbilClient",
    "MustakbilError",
    "MustakbilFetchError",
    "MustakbilParseError",
    "MustakbilParser",
    "MustakbilPipeline",
    "MustakbilPipelineRunResult",
    "MustakbilResponseError",
    "MustakbilSettings",
    "RawMustakbilJob",
]
