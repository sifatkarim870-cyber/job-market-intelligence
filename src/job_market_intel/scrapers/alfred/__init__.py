"""Alfred (alfred.is) -- the Icelandic job board.

Why this source exists
----------------------
Iceland had **no** postings in the corpus. Alfred is the country's dominant
board and needs no API key, no registration and no proxy.

The one thing worth knowing before writing any of this
------------------------------------------------------
Alfred's homepage embeds what looks like a complete job feed in
``__NEXT_DATA__``: ``props.pageProps.jobs``, reporting ``totalCount: 572`` and
``totalPages: 22``. Scraping that is the obvious move and it cannot work:

* it serves only **27** records per response;
* every pagination attempt returns a **byte-identical** 667,028-byte page with
  **0 new** ids -- ``/?page=2``, ``/?p=2`` and ``/?page=3`` are all page 1,
  because the page is statically generated;
* ``/starf?page=2`` and ``/page/2`` are HTTP 404.

robots.txt disallows ``/api/*`` and every filter parameter (``*jobtypes=*``,
``*tags=*``, ``*zips=*``, ``*cat=*``), so the JSON API -- the one path that
would have made the whole feed reachable in a handful of requests -- and the
faceted views are both unavailable by the site's own rules.

What robots *does* nominate is ``Sitemap: https://alfred.is/sitemap.xml``. That
index has two children, and ``sitemap-jobs.xml`` holds **624** ``/starf/``
URLs. So discovery reads the sitemap: it is both the compliant route and the
only one that reaches the whole board. A crawler that trusted the homepage feed
would have collected 27 postings and reported success.

The payload
-----------
A top-level schema.org ``JobPosting`` on each detail page. Measured over 10
postings on 2026-10-16:

* 9 of 10 fields on every posting -- ``title``, ``description``,
  ``datePosted``, ``validThrough``, ``hiringOrganization``, ``directApply``,
  ``employmentType``;
* ``jobLocation`` on 7 of 10, always ``addressCountry: "Iceland"`` (a country
  *name*, where apna and mustakbil both use an ISO code);
* descriptions of 17-2656 characters, in Icelandic, ``<p>``-wrapped;
* ``employmentType`` FULL_TIME 9, PART_TIME 1;
* ``hiringOrganization.logo`` a plain URL string.

Two absences are facts about the board rather than parser gaps, and both shape
the design:

* **No ``identifier`` (0 of 10).** Nothing in the payload names the posting, so
  the URL slug is the key. That is also what makes re-runs idempotent.
* **No ``baseSalary`` (0 of 10).** Alfred publishes no salary, so every row has
  ``salary_disclosed = False`` and no ``pay_period`` is claimed about a figure
  that does not exist. This is the one source in the corpus where that is true,
  and the coverage number should be read as a fact about Iceland's job market
  reporting, not as a scraper limitation.

``validThrough`` is nullable in the source, so ``closing_date`` is too. The
postings are in Icelandic; the corpus already carries ``language_code`` and a
scheduled translation kernel for that, and nothing is translated at scrape
time.

General-application pages
-------------------------
A few sitemap entries are not vacancies: ``/starf/almenn-umsokn-1`` ("general
application") carries 591 characters describing the employer's business rather
than a role. These are dropped before validation and counted in the run result
as ``general_application_dropped``, so the exclusion shows up in the summary
instead of quietly shrinking the batch.

Compliance
----------
robots.txt is real ``text/plain``, 157 bytes, and the governing ``User-agent: *``
group is ``Allow: /*``. Only ``/api/*`` and the four filter parameters are
disallowed, none of which this scraper requests; the sitemap is the route the
site nominates for crawlers.

Requests are sent at 1.0s intervals with an identifying User-Agent. Detail
pages are 240-250 KB, among the largest served in this project, so the page cap
is the request-budget knob.

Typical usage::

    from job_market_intel.scrapers.alfred import AlfredClient, AlfredParser

    records, failures = AlfredClient().fetch_raw_jobs()
    jobs, issues = AlfredParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.alfred.client import AlfredClient
from job_market_intel.scrapers.alfred.config import AlfredSettings
from job_market_intel.scrapers.alfred.exceptions import (
    AlfredError,
    AlfredFetchError,
    AlfredParseError,
    AlfredResponseError,
)
from job_market_intel.scrapers.alfred.models import RawAlfredJob
from job_market_intel.scrapers.alfred.parser import AlfredParser
from job_market_intel.scrapers.alfred.pipeline import (
    AlfredPipeline,
    AlfredPipelineRunResult,
)

__all__ = [
    "AlfredClient",
    "AlfredError",
    "AlfredFetchError",
    "AlfredParseError",
    "AlfredParser",
    "AlfredPipeline",
    "AlfredPipelineRunResult",
    "AlfredResponseError",
    "AlfredSettings",
    "RawAlfredJob",
]
