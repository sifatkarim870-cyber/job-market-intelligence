"""Job in Rwanda (jobinrwanda.com) -- a Rwandan job board.

Why this source exists
----------------------
Rwanda had **no** postings in the corpus. Job in Rwanda carries **199 postings
on a single page** and needs no API key, no registration and no proxy. It is the
largest single-country win measured so far.

This board publishes no structured data
---------------------------------------
No schema.org JSON-LD, no ``og:`` meta tags. Everything is markup extraction:

* ``<title>`` is ``"<Job Title> | Job in Rwanda"`` -- split on the trailing bar.
* ``.node__content`` is the posting body.
* ``.field--name-body`` is site boilerplate ("Click on the APPLY button to send
  your application documents: ...") and is removed, because leaving it in would
  make that sentence the description of every posting.

Discovery is the **homepage**
----------------------------
``/jobs`` is **HTTP 404** and ``/?page=2`` returns 0 new postings -- there is no
pager. All 199 postings are on one page, so the whole board is one request. The
hrefs are **relative** (199 relative, 0 absolute); the pattern accepts both
spellings because Angola Emprego was the opposite way round and a relative-only
pattern there matched nothing at all.

The trap, and it is one of omission
-----------------------------------
**There is no posting date anywhere on the site.** Six detail pages were
inspected: four carry no date at all, and the two that do carry one only ever
carry a **deadline**, in prose::

    "The deadline for submission of applications is 19 October 2026 at 5:00 PM"
    "Application deadline Sunday 25 October 2026 - places filled on a rolling basis"
    "Application Deadline 28 November 2026 ."

A regex that grabbed the first date on the page would have written a **closing**
date into ``posting_date`` on every row that had one, asserting a recency the
site never claims -- and every downstream "how fresh is this corpus" question
would then be answered with a lie. So ``posted_date`` is ``None`` on every Job
in Rwanda row, and only a date inside deadline wording is recorded, as
``closing_date``. The matched phrase is kept in ``raw_payload["deadline_phrase"]``
so the extraction can be audited.

**There is no company field either.** The employer appears only inside the
posting prose ("The Management of RATWA SACCO HUYE informs all qualified and
competent candidates..."), which is a sentence rather than a field, so
``company_name`` stays "Unknown employer" instead of putting unverifiable
strings into ``core.companies``.

No salary and no location field are published, so ``SOURCE_HOME_COUNTRY``
supplies ``RW`` and ``salary_disclosed`` is always ``False``.

Any freshness analysis over this corpus has to treat Job in Rwanda as
undated rather than reading its NULL ``posting_date`` as "unknown".

Compliance
----------
robots.txt is real ``text/plain``, 1706 bytes. ``User-agent: *`` allows ``/`` and
disallows only ``/core/``, ``/profiles/`` and ``/README.txt``. Job pages are
permitted.

Typical usage::

    from job_market_intel.scrapers.jobinrwanda import JobInRwandaClient, JobInRwandaParser

    records, failures = JobInRwandaClient().fetch_raw_jobs()
    jobs, issues = JobInRwandaParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.jobinrwanda.client import JobInRwandaClient
from job_market_intel.scrapers.jobinrwanda.config import JobInRwandaSettings
from job_market_intel.scrapers.jobinrwanda.exceptions import (
    JobInRwandaError,
    JobInRwandaFetchError,
    JobInRwandaParseError,
    JobInRwandaResponseError,
)
from job_market_intel.scrapers.jobinrwanda.models import RawJobInRwandaJob
from job_market_intel.scrapers.jobinrwanda.parser import JobInRwandaParser, parse_detail
from job_market_intel.scrapers.jobinrwanda.pipeline import (
    JobInRwandaPipeline,
    JobInRwandaPipelineRunResult,
)

__all__ = [
    "JobInRwandaClient",
    "JobInRwandaError",
    "JobInRwandaFetchError",
    "JobInRwandaParseError",
    "JobInRwandaParser",
    "JobInRwandaPipeline",
    "JobInRwandaPipelineRunResult",
    "JobInRwandaResponseError",
    "JobInRwandaSettings",
    "RawJobInRwandaJob",
    "parse_detail",
]
