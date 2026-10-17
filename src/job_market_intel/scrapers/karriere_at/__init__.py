"""Karriere.at (karriere.at) -- an Austrian job board.

Why this source exists
----------------------
Austria had **no** postings in the corpus. Karriere.at needs no key, no
registration and no proxy, and paginates (well, it lists 15 postings on one
page with no working pager).

No structured-data gap
----------------------
The detail page carries a schema.org ``JobPosting`` with ``title``,
``description`` (HTML), ``datePosted`` (with timezone offset),
``employmentType`` (a **list**), ``hiringOrganization`` (name + ``sameAs``),
``identifier`` (``PropertyValue``, value is a **string**), ``jobLocation`` (an
**array** of ``Place``), ``baseSalary`` (EUR, nested ``value.value`` shape) and
``directApply``. **No ``industry``** on the measured postings.

Traps, each measured 2026-10-18
-------------------------------
1. ``employmentType`` is a **list** (``[\"PART_TIME\"]``) -- the same shape as
   Angola Emprego, not the bare string Jobweb Ghana sends.
2. ``identifier`` is a ``PropertyValue`` whose ``value`` is a **string**
   (\"10035663\"), not an int.
3. ``jobLocation`` is an **array** of ``Place``.
4. ``baseSalary`` nests ``value``/``minValue``/``maxValue``/``unitText`` under
   ``value`` -- the Apna/Mustakbil shape, a **seventh** distinct layout.
5. ``datePosted`` carries a timezone offset (\"2026-10-17T08:23:08+02:00\").
6. ``description`` is HTML.

Compliance
----------
robots.txt: ``User-agent: *`` group is empty (allow all). Only ``BLEXBot`` and
``AhrefsBot`` are blocked.

Typical usage::

    from job_market_intel.scrapers.karriere_at import KarriereAtClient, KarriereAtParser

    records, failures = KarriereAtClient().fetch_raw_jobs()
    jobs, issues = KarriereAtParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.karriere_at.client import KarriereAtClient
from job_market_intel.scrapers.karriere_at.config import KarriereAtSettings
from job_market_intel.scrapers.karriere_at.exceptions import (
    KarriereAtError,
    KarriereAtFetchError,
    KarriereAtParseError,
    KarriereAtResponseError,
)
from job_market_intel.scrapers.karriere_at.models import RawKarriereAtJob
from job_market_intel.scrapers.karriere_at.parser import KarriereAtParser
from job_market_intel.scrapers.karriere_at.pipeline import (
    KarriereAtPipeline,
    KarriereAtPipelineRunResult,
)

__all__ = [
    "KarriereAtCleaner",
    "KarriereAtClient",
    "KarriereAtError",
    "KarriereAtFetchError",
    "KarriereAtParseError",
    "KarriereAtParser",
    "KarriereAtPipeline",
    "KarriereAtPipelineRunResult",
    "KarriereAtResponseError",
    "KarriereAtSettings",
    "RawKarriereAtJob",
]
