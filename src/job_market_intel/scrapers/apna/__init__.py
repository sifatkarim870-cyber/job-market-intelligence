"""Apna (apna.co) -- the largest Indian job board.

Why this source exists
----------------------
India had **no** postings in the corpus. The existing sources cover Iran
(jobinja, jobvision, irantalent), Israel, Armenia, Mauritius, Georgia,
Canada, the US, China (51job), South-East Asia (glints) and South Africa
(careers24, added the same day) -- but nothing in India, which is the largest
labour market in the world by headcount and third by GDP.

It is also the **best salary source in the corpus**, by a wide margin:

* ``baseSalary`` on **30 of 30** postings measured. Every one a
  ``minValue``/``maxValue`` band in INR. (For comparison: careers24 15/40,
  Built In ~3/4, and greenhouse, arbeitnow, indeed and weworkremotely store 0
  amounts across 6575, 353, 168 and 90 salary rows respectively.)
* ``skills`` -- a list of 0-11 real skill strings -- on 15 of 30. Every other
  source in this project writes an empty list to ``CleanedJob.skills``, so
  these are the only rows whose skills column means anything.

No key, no registration, no proxy, which puts it in the buildable set while
LinkedIn, Naukri, Foundit, Cutshort and Internshala are not.

The shapes that differ from every sibling source
------------------------------------------------
Four distinct ``baseSalary`` layouts now exist in this codebase, and the
parser probes every plausible position rather than assuming one:

* **Wellfound / Built In** -- ``value.minValue`` / ``value.maxValue``.
* **Careers24** -- ``value.value``, a bare scalar, no band.
* **Apna** -- ``value.value.minValue`` / ``value.value.maxValue``: a band
  nested one level deeper, inside a ``QuantitativeValue``.

Other measured differences:

* ``identifier.value`` is a JSON **number** (670861231), not a string.
* ``addressCountry`` is the ISO code ``"IN"``, not a country name.
* ``hiringOrganization.logo`` is a plain URL string. (Built In emits an
  ``ImageObject`` dict here.)
* The ``JobPosting`` is at the top level, not nested under ``@graph``.

One measurement that will otherwise look like a bug: Apna writes **"Bengaluru"**
where ``ref.cities`` holds **"Bangalore"**. Both are correct names for the same
city, so ``city_exact`` will not match on the spelling and Bengaluru postings
resolve to their state or to country-only. That is a seed-data gap, not a
parser fault, and it is deliberately left visible rather than papered over with
a hardcoded alias table.

Descriptions run 23-4282 characters (mean 835) and **16 of 30 are under 100
characters**. The usual 100-character "substantial description" gate would
therefore fail more than half of a healthy batch, so the validator's floor is
set just under the measured minimum. That reasoning is in
:mod:`.validator` and is worth reading before changing the number.

Compliance
----------
robots.txt is real ``text/plain``, 160 bytes. The governing ``User-agent: *``
group disallows exactly one path, ``/*.infra.apna.co/``, which is an internal
infrastructure host and not part of the job surface. ``/jobs``,
``/job/<city>/<slug>-<id>``, ``/company`` and ``/search`` are all fetchable,
confirmed with ``urllib.robotparser``. Only ``/jobs`` and ``/job/...`` are
requested.

Measured 2026-10-16: 25 postings per page and a pager that genuinely works --
150 distinct paths over 6 pages with 25 new on every page. Listing pages are
~1.0 MB, among the largest served here, so the page cap is the request-budget
knob.

Requests are sent at 1.2s intervals with an identifying User-Agent.

Typical usage::

    from job_market_intel.scrapers.apna import ApnaClient, ApnaParser

    records, failures = ApnaClient().fetch_raw_jobs()
    jobs, issues = ApnaParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.apna.client import ApnaClient
from job_market_intel.scrapers.apna.config import ApnaSettings
from job_market_intel.scrapers.apna.exceptions import (
    ApnaError,
    ApnaFetchError,
    ApnaParseError,
    ApnaResponseError,
)
from job_market_intel.scrapers.apna.models import RawApnaJob
from job_market_intel.scrapers.apna.parser import ApnaParser
from job_market_intel.scrapers.apna.pipeline import (
    ApnaPipeline,
    ApnaPipelineRunResult,
)

__all__ = [
    "ApnaClient",
    "ApnaError",
    "ApnaFetchError",
    "ApnaParseError",
    "ApnaParser",
    "ApnaPipeline",
    "ApnaPipelineRunResult",
    "ApnaResponseError",
    "ApnaSettings",
    "RawApnaJob",
]
