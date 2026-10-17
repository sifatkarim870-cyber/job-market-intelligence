"""Jobs.af (jobs.af) -- an Afghan job board.

Why this source exists
----------------------
Adds a second, independent Afghan board alongside ACBAR, with a different
employer base and a different markup. No key, no registration, no proxy.

Discovery is the homepage
------------------------
``/public/job/page/2`` is **HTTP 404**, ``/public/job?page=2`` adds 0 new, and
re-fetching ``/`` adds 0 new. There is **no pager**: all **12** postings are on
one page, so the whole board is a single request. Hrefs are **relative** (measured
12 relative, 0 absolute); the host prefix in the pattern is optional, because
Angola Emprego was the opposite way round and a relative-only pattern there
matched nothing at all on a board serving 15 postings a page.

Two traps
---------
1. **``addressCountry`` is the name ``"Afghanistan"``, not the ISO code ``"AF"``**
   -- the same shape as Vagas.com.br's ``"Brasil"`` and with the same
   consequence. ``geographic_resolution`` matches on ISO codes, so an unmapped
   name resolves to *no country* and the row silently collapses onto the
   global-remote location. The cleaner normalizes it and keeps the raw value for
   audit.

2. **``datePosted`` carries milliseconds and a truncated offset** --
   ``"2026-10-17 10:48:27.175+00"``. That is not ISO 8601 (``+00`` has no
   minutes), so ``datetime.fromisoformat`` rejects it on 3.10 and earlier and a
   strict parser returns **no dates at all**. The parser therefore takes the
   leading ``YYYY-MM-DD`` by regex, which is robust to whatever the tail looks
   like. ``validThrough`` is ``"2026-10-30 00:00:00+00"``, the same shape without
   milliseconds.

Also measured: ``employmentType`` is the bare string ``"FULL_TIME"``;
``hiringOrganization`` carries a name and a ``logo``; **no ``identifier``**, so the
URL slug is the key; and **no ``baseSalary``**, so no salary is stored.

``directApply`` is ``true`` on the measured posting. The corpus has no column for
it, so it is recorded in ``raw_payload`` rather than invented as a schema change.

Compliance
----------
robots.txt is real ``text/plain``, 661 bytes. ``User-agent: *`` is ``Allow: /``
and disallows only ``/dashboard``, ``/discover``, ``/talents``, ``/projects`` and
``/wallet``. ``/public/job/`` is permitted.

Typical usage::

    from job_market_intel.scrapers.jobs_af import JobsAfClient, JobsAfParser

    records, failures = JobsAfClient().fetch_raw_jobs()
    jobs, issues = JobsAfParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.jobs_af.client import JobsAfClient
from job_market_intel.scrapers.jobs_af.config import JobsAfSettings
from job_market_intel.scrapers.jobs_af.exceptions import (
    JobsAfError,
    JobsAfFetchError,
    JobsAfParseError,
    JobsAfResponseError,
)
from job_market_intel.scrapers.jobs_af.models import RawJobsAfJob
from job_market_intel.scrapers.jobs_af.parser import JobsAfParser
from job_market_intel.scrapers.jobs_af.pipeline import (
    JobsAfPipeline,
    JobsAfPipelineRunResult,
)

__all__ = [
    "JobsAfCleaner",
    "JobsAfClient",
    "JobsAfError",
    "JobsAfFetchError",
    "JobsAfParseError",
    "JobsAfParser",
    "JobsAfPipeline",
    "JobsAfPipelineRunResult",
    "JobsAfResponseError",
    "JobsAfSettings",
    "RawJobsAfJob",
]
