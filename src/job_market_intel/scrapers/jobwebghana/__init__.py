"""Jobweb Ghana (jobwebghana.com) -- a Ghanaian job board.

Why this source exists
----------------------
Ghana had **no** postings in the corpus. Jobweb Ghana needs no API key, no
registration and no proxy, and paginates properly -- ``/jobs/`` carries 22
postings and ``/jobs/page/2/`` adds 13 more.

Structured data, but only on the detail page
---------------------------------------------
An early triage scored this board "HTML extraction needed, no structured data"
because the **listing** page carries only a ``BreadcrumbList``. The
``JobPosting`` is on each **detail** page. A board is only proven to lack
structured data once a detail page has been probed, and this one had not been.

Measured on 5 postings, the payload carries ``title``, ``description``,
``datePosted`` (no timezone), ``validThrough``, ``employmentType``
(``"FULL_TIME"``, a bare string), ``hiringOrganization`` (name + ``sameAs``),
``jobLocation`` (streetAddress, locality, postalCode, region) and
``baseSalary``. **No ``identifier``**, so the URL slug is the key.

The salary is a site-wide placeholder, and is rejected
------------------------------------------------------
**5 of 5 measured postings carry a byte-identical** ``baseSalary``::

    {"currency": "GHS",
     "value": {"value": "1500", "minValue": "1500", "maxValue": "8000",
               "unitText": "MONTH"}}

The five span a Chief Executive Officer, a CCTV Controller and an Accounts
Clerk. Those roles do not share a band, and the redundant ``value`` duplicating
``minValue`` is the signature of a site template rather than a posted figure.

Storing it would put the same invented 1500-8000 GHS band on **every** Ghanaian
row, inside a well-formed schema.org block -- so nothing downstream would flag
it, and every salary statistic computed over Ghana would be quietly wrong in the
most believable direction available: a plausible number, in the right currency,
in the right period. It is recorded in ``raw_payload`` for audit and not stored,
which is the treatment CareerJunction's ``"R Undisclosed"`` already gets.

Hrefs and robots
----------------
Hrefs are **absolute** (measured 20 absolute, 0 relative), so the host prefix in
the link pattern is optional -- Angola Emprego was the same way and a
relative-only pattern there matched nothing on a board serving 15 postings a
page. robots.txt disallows ``/*?*``, i.e. every query string, so pagination uses
the **path** form ``/jobs/page/2/`` and never ``?page=2``.

Typical usage::

    from job_market_intel.scrapers.jobwebghana import (
        JobwebGhanaClient, JobwebGhanaParser,
    )

    records, failures = JobwebGhanaClient().fetch_raw_jobs()
    jobs, issues = JobwebGhanaParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.jobwebghana.client import JobwebGhanaClient
from job_market_intel.scrapers.jobwebghana.config import JobwebGhanaSettings
from job_market_intel.scrapers.jobwebghana.exceptions import (
    JobwebGhanaError,
    JobwebGhanaFetchError,
    JobwebGhanaParseError,
    JobwebGhanaResponseError,
)
from job_market_intel.scrapers.jobwebghana.models import (
    _SITE_DEFAULT_SALARY,
    RawJobwebGhanaJob,
)
from job_market_intel.scrapers.jobwebghana.parser import JobwebGhanaParser
from job_market_intel.scrapers.jobwebghana.pipeline import (
    JobwebGhanaPipeline,
    JobwebGhanaPipelineRunResult,
)

__all__ = [
    "JobwebGhanaClient",
    "JobwebGhanaError",
    "JobwebGhanaFetchError",
    "JobwebGhanaParseError",
    "JobwebGhanaParser",
    "JobwebGhanaPipeline",
    "JobwebGhanaPipelineRunResult",
    "JobwebGhanaResponseError",
    "JobwebGhanaSettings",
    "RawJobwebGhanaJob",
    "_SITE_DEFAULT_SALARY",
]
