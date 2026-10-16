"""Net-Empregos (net-empregos.com) -- the Portuguese job board.

Why this source exists
----------------------
Portugal had **no** postings in the corpus. Net-Empregos is the country's
largest general board and needs no API key, no registration and no proxy.

The one thing worth knowing before writing any of this
------------------------------------------------------
Net-Empregos publishes a schema.org ``JobPosting`` in a ``<script
type="application/ld+json">`` block on each detail page, and the JSON is
**malformed**: the ``description`` string contains raw newlines, which makes
``json.loads`` raise ``Invalid control character``. A strict parser reads
nothing at all from every page -- which is exactly what the first probe
reported, before the fix was found. The fix is ``json.loads(block,
strict=False)``, which tolerates control characters inside strings. Every field
extracts cleanly that way.

Discovery is **breadth by page**: ``/jobs`` returns 18 posting ids and
``?page=2`` gives 18 new ones, so the pager is real. Detail URLs are
``/jobs/<id>/<slug>/`` where the id is 6-12 digits.

The payload
-----------
Measured over 3 postings on 2026-10-16:

* 8 of 8 fields on every posting -- ``title``, ``description``, ``datePosted``,
  ``validThrough``, ``employmentType``, ``hiringOrganization`` (name + logo),
  ``jobLocation`` (address with locality, region, country, postalCode,
  streetAddress), ``industry``;
* ``addressCountry: "PT"``, an ISO code;
* descriptions of 3400+ characters, in Portuguese, ``<b>``/``<BR>``-wrapped;
* ``employmentType`` FULL_TIME.

Two absences are facts about the board rather than parser gaps, and both shape
the design:

* **No ``identifier``.** Nothing in the payload names the posting, so the URL id
  is the key. That is also what makes re-runs idempotent.
* **No ``baseSalary``.** Net-Empregos publishes no salary, so every row has
  ``salary_disclosed = False`` and no ``pay_period`` is claimed about a figure
  that does not exist. This is one of two sources in the corpus where that is
  true (the other is Alfred), and the coverage number should be read as a fact
  about Portuguese job postings, not as a scraper limitation.

Compliance
----------
robots.txt returns **HTTP 406 as text/html** -- not a real robots file, so
under RFC 9309 there is no restriction to parse. ``/jobs`` and
``/jobs/<id>/<slug>/`` are both fetchable.

Requests are sent at 1.0s intervals with an identifying User-Agent. Detail
pages are 80-90 KB, among the largest served in this project, so the page cap
is the request-budget knob.

Typical usage::

    from job_market_intel.scrapers.net_empregos import NetEmpregosClient, NetEmpregosParser

    records, failures = NetEmpregosClient().fetch_raw_jobs()
    jobs, issues = NetEmpregosParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.net_empregos.client import NetEmpregosClient
from job_market_intel.scrapers.net_empregos.config import NetEmpregosSettings
from job_market_intel.scrapers.net_empregos.exceptions import (
    NetEmpregosError,
    NetEmpregosFetchError,
    NetEmpregosParseError,
    NetEmpregosResponseError,
)
from job_market_intel.scrapers.net_empregos.models import RawNetEmpregosJob
from job_market_intel.scrapers.net_empregos.parser import NetEmpregosParser
from job_market_intel.scrapers.net_empregos.pipeline import (
    NetEmpregosPipeline,
    NetEmpregosPipelineRunResult,
)

__all__ = [
    "NetEmpregosClient",
    "NetEmpregosError",
    "NetEmpregosFetchError",
    "NetEmpregosParseError",
    "NetEmpregosParser",
    "NetEmpregosPipeline",
    "NetEmpregosPipelineRunResult",
    "NetEmpregosResponseError",
    "NetEmpregosSettings",
    "RawNetEmpregosJob",
]
