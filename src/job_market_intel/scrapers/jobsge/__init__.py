"""Jobs.ge (jobs.ge) -- a Georgian job board.

Why this source exists
----------------------
Georgia already has 3,628 postings, all from ``hrge``. Jobs.ge is a second
Georgian board with a different shape -- advertising-classifieds rather than a
public employment service -- so it adds postings rather than duplicating them.

It was the first item on the "needs a second look" list in
``docs/source_registration_list.md``, left there by an earlier verdict that
called its ``/ge/?view=jobs&id=...`` links "a locale prefix, not a posting
path". That was wrong: the query string is the ad id and the pages are
postings. The third headless-browser source.

Traps, each measured 2026-10-18
-------------------------------
1. **The English detail page is a stub.** ``/en/?view=jobs&id=N`` renders the
   title, the employer and one sentence, then "See full text of this
   announcement in Georgian." -- 548 characters for the same posting whose
   Georgian page is 4,421. The listing and the English titles come from
   ``/en/``; the description comes from ``/ge/``.
2. **The ad id is a query parameter**, not a path segment:
   ``/en/?view=jobs&id=761321``.
3. **The listing is a plain HTML table**, not a card list, with the header
   ``* | VIP Advertisements | | Provided By | Published | Deadline``.
4. **Dates are Georgian month names with no year**, on one line:
   ``გამოქვეყნდა: 16 ოქტომბერი / ბოლო ვადა: 16 ნოემბერი``.
5. **The description is the largest table row that is not a label.** The same
   table holds the nav chrome, a "Forward Link" row, and repeats of the
   labelled rows.
6. **No salary and no location fields.** Both appear only in prose -- pay
   mixed with internship rates in one ad, Tbilisi inside the body text.
   Neither is scraped.

Compliance
----------
robots.txt: ``User-agent: *`` / ``Allow: /`` -- the whole site is permitted.
"""

from __future__ import annotations

from job_market_intel.scrapers.jobsge.client import JobsGeClient
from job_market_intel.scrapers.jobsge.config import JobsGeSettings
from job_market_intel.scrapers.jobsge.exceptions import (
    JobsGeError,
    JobsGeFetchError,
    JobsGeParseError,
    JobsGeResponseError,
)
from job_market_intel.scrapers.jobsge.models import RawJobsGeJob
from job_market_intel.scrapers.jobsge.parser import (
    JobsGeParser,
    parse_detail,
    parse_english_date,
    parse_georgian_date,
    parse_listing,
    split_published_deadline,
)
from job_market_intel.scrapers.jobsge.pipeline import (
    JobsGePipeline,
    JobsGePipelineRunResult,
)

__all__ = [
    "JobsGeCleaner",
    "JobsGeClient",
    "JobsGeError",
    "JobsGeFetchError",
    "JobsGeParseError",
    "JobsGeParser",
    "JobsGePipeline",
    "JobsGePipelineRunResult",
    "JobsGeResponseError",
    "JobsGeSettings",
    "RawJobsGeJob",
    "parse_detail",
    "parse_english_date",
    "parse_georgian_date",
    "parse_listing",
    "split_published_deadline",
]
