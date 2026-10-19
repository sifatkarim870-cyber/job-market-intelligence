"""Forasna (forasna.com) -- Egypt's largest job board.

Why this source exists
----------------------
Egypt had **one** posting in the corpus, from a board that happened to list
one. Forasna is the country's largest job board and reports **2,852
postings**. It is unwalled, needs no key, and needs no browser.

Traps, each measured 2026-10-19
-------------------------------
1. **The nominal all-jobs route has no postings on it.** ``/a/وظائف-مصر``
   returns HTTP 200 and 281 KB with **zero** ``/job/p/`` links and no
   pagination. The site's own search page ``/وظائف-خالية`` is the listing
   that works, and it is a single ordered stream rather than an overlapping
   set of category pages.
2. **Pagination is an offset**, ``?start=20``, not a page number -- 20
   postings a page, the last page at ``?start=2840``.
3. **The id is the trailing number of the URL slug**
   (``/job/p/<arabic-slug>-444468``), and the JSON-LD ``identifier.value``
   agrees. The ids are **not** dense -- 2,000 consecutive postings span
   303,860 to 444,468 -- so enumerating ids is not an option.
4. **The currency is per posting.** 18 of 60 sampled postings declare EGP
   and one declares **USD** on an Egyptian board. Assuming EGP would
   mis-file the dollar one.
5. **``addressRegion`` can name a governorate of another country.** One
   sampled posting's region is "أبها" -- Abha, in **Saudi Arabia** -- so the
   country is taken from ``addressCountry`` and never from the region.
6. **27% of postings have no body.** The employer left the description empty
   and the page shows only a structured requirements block, which is not a
   description and is not stored as one.
7. **Arabic spellings are inconsistent** -- the same place appears as both
   "ابو حماد" and "أبو رواش" -- so exact city matching is partial by
   nature and is not papered over.

The detail page's schema.org ``JobPosting`` carries everything else:
``title``, ``identifier``, ``datePosted``, ``validThrough``,
``employmentType``, ``hiringOrganization.name``, ``jobLocation.address`` and,
on 32% of postings, a real ``baseSalary`` in EGP (or USD) per month.

Compliance
----------
robots.txt: ``User-agent: *`` with no ``Disallow``.
"""

from __future__ import annotations

from job_market_intel.scrapers.forasna.client import ForasnaClient
from job_market_intel.scrapers.forasna.config import ForasnaSettings
from job_market_intel.scrapers.forasna.exceptions import (
    ForasnaError,
    ForasnaFetchError,
    ForasnaParseError,
    ForasnaResponseError,
)
from job_market_intel.scrapers.forasna.models import (
    EMPLOYMENT_TYPES,
    UNIT_TO_PAY_PERIOD,
    RawForasnaJob,
)
from job_market_intel.scrapers.forasna.parser import (
    ForasnaParser,
    parse_detail,
    parse_listing,
    slug_id,
)
from job_market_intel.scrapers.forasna.pipeline import (
    ForasnaPipeline,
    ForasnaPipelineRunResult,
)

__all__ = [
    "EMPLOYMENT_TYPES",
    "ForasnaCleaner",
    "ForasnaClient",
    "ForasnaError",
    "ForasnaFetchError",
    "ForasnaParseError",
    "ForasnaParser",
    "ForasnaPipeline",
    "ForasnaPipelineRunResult",
    "ForasnaResponseError",
    "ForasnaSettings",
    "RawForasnaJob",
    "UNIT_TO_PAY_PERIOD",
    "parse_detail",
    "parse_listing",
    "slug_id",
]
