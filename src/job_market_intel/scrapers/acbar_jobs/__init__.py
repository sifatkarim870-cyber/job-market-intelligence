"""ACBAR jobs (acbar.org) -- an Afghan relief-sector job board.

Why this source exists
----------------------
Afghanistan had **no** postings in the corpus. ACBAR is the Afghan Relief and
Development Coordination body's job board, needs no key, no registration and no
proxy, and paginates: ``/en/jobs`` gives **20** postings and ``?page=2`` gives 20
new ones.

Structured data, but none of it is schema.org
----------------------------------------------
No JSON-LD, no ``og:`` meta tags. Everything is a ``<dl>`` of label/value rows::

    <div class="acbar-jd__info-row">
      <dt class="acbar-jd__info-term">Published</dt>
      <dd class="acbar-jd__info-desc">2026-10-14</dd>
    </div>

Measured keys: ``Type``, ``Location``, ``Category``, ``Published``,
``Nationality``, ``Gender``, ``Salary``, ``Contract Duration``,
``Vacancy Number``, ``No of Job``, plus ``Education`` and ``Experience`` in a
second pair shape. The closing date is separate, in
``.acbar-jd__deadline-label`` / ``.acbar-jd__deadline-value``.

The trap: the body contains other postings
------------------------------------------
``.acbar-jd__body`` is 4680 characters and holds **six** ISO dates -- all of them
belonging to *other* jobs, inside a ``.acbar-jd__related`` carousel. The tell was
that the same ten dates came back from two *different* posting pages. A naive
"first date in the body" extraction therefore assigns a deadline from an unrelated
job and splices six strangers into the description.

The related block is removed before the body text is taken; after that **zero**
dates remain, and ``raw_payload["dates_left_in_body"]`` records that count so the
removal is auditable rather than assumed.

Two things that look like data and are not
------------------------------------------
* **``Salary`` is prose.** Measured: ``"As Per Organization"``, ``"As per scale"``,
  ``"Negotiable"``. Nothing is stored; the verbatim string is kept in
  ``raw_payload["salary_text"]``.
* **``Nationality`` is not a country.** It reads ``"Afghan"`` or ``"National"``
  and describes *who may apply*, not where the job is. It is preserved verbatim
  and deliberately not used to derive the country; ``SOURCE_HOME_COUNTRY``
  supplies ``AF``.

There is no company field -- the employer appears only in the body prose
("Company Profile - Peyawray Rubaat Manufacturing Company") -- so
``company_name`` stays "Unknown employer".

Pagination, carefully
---------------------
``?page=N`` is the pager. ``/en/site-page/N`` is HTTP 404: that is the
pagination *chrome*, not the pager, and mistaking one for the other is the
obvious way to conclude the board does not paginate. Hrefs are **absolute**
(measured 20 absolute, 0 relative) so the host prefix in the link pattern is
optional.

Compliance
----------
robots.txt is 24 bytes: ``User-agent: *`` with an empty ``Disallow:``. The whole
site is permitted.

Typical usage::

    from job_market_intel.scrapers.acbar_jobs import AcbarJobsClient, AcbarJobsParser

    records, failures = AcbarJobsClient().fetch_raw_jobs()
    jobs, issues = AcbarJobsParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.acbar_jobs.client import AcbarJobsClient
from job_market_intel.scrapers.acbar_jobs.config import AcbarJobsSettings
from job_market_intel.scrapers.acbar_jobs.exceptions import (
    AcbarJobsError,
    AcbarJobsFetchError,
    AcbarJobsParseError,
    AcbarJobsResponseError,
)
from job_market_intel.scrapers.acbar_jobs.models import RawAcbarJobsJob
from job_market_intel.scrapers.acbar_jobs.parser import AcbarJobsParser, parse_detail
from job_market_intel.scrapers.acbar_jobs.pipeline import (
    AcbarJobsPipeline,
    AcbarJobsPipelineRunResult,
)

__all__ = [
    "AcbarJobsClient",
    "AcbarJobsCleaner",
    "AcbarJobsError",
    "AcbarJobsFetchError",
    "AcbarJobsParseError",
    "AcbarJobsParser",
    "AcbarJobsPipeline",
    "AcbarJobsPipelineRunResult",
    "AcbarJobsResponseError",
    "AcbarJobsSettings",
    "RawAcbarJobsJob",
    "parse_detail",
]
