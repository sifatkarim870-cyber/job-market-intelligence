"""Shine.com (shine.com) -- an Indian job board.

Why this source exists
----------------------
India had ZERO postings in the corpus before this. Shine.com is a large
Indian board (8L+ live roles per its own marketing) with no Cloudflare,
no registration wall, and no proxy requirement -- so it sits in the
buildable set.

It was probed on 2026-10-20 and confirmed:

1. **Server-rendered HTML, no browser.** The listing page
   ``/job-search/jobs-in-india`` returns full markup with job links; no
   Playwright needed.
2. **Real pagination.** The listing carries ``rel="next"`` to
   ``/job-search/india-jobs-2`` and each page adds new ids (measured:
   page 1 = 40 jobs, page 2 = more with no overlap).
3. **Detail URL is an id-keyed path**::
       /jobs/<slug>/<company-slug>/<numeric_job_id>
   e.g. ``/jobs/revenue-assurance/airtel-india/19525849``. The numeric
   id is the natural key.
4. **JSON-LD JobPosting on every detail page**, top-level (not @graph):
   title, hiringOrganization.name, identifier.value (numeric id), url,
   datePosted, validThrough (deadline), employmentType,
   experienceRequirements.monthsOfExperience, jobLocation
   (addressCountry ISO 'IN', addressLocality), skills list, industry.
5. **No __NEXT_DATA__** -- it is a Next.js app but the data ships in
   schema.org JSON-LD, not in a hydration blob.
6. **robots.txt**: ``User-agent: *`` / ``Allow: /`` -- the whole site is
   permitted.

Traps this scraper exists to avoid
----------------------------------
* **Empty descriptions.** Some postings render "No job description at the
  moment!" in the JSON-LD. Those rows get description=None and an honest
  quality score rather than invented text.
* **Year-less relative dates are absent.** datePosted and validThrough
  are full ISO timestamps with a +05:30 offset -- parse them directly.
* **Salary is a band with unitText.** Measured postings read "INR 0+
  (Annual)" but unitText says MONTH -- pay_period=monthly, currency=INR,
  and the numeric bounds come from baseSalary.value.minValue/maxValue
  when present.
* **addressCountry is the ISO code 'IN'** -- geographic_resolution matches
  on ISO codes, so no normalization trap here.

Compliance
----------
robots.txt: ``User-agent: *`` / ``Allow: /`` -- the whole site is permitted.
"""

from __future__ import annotations

from job_market_intel.scrapers.shine.client import ShineClient
from job_market_intel.scrapers.shine.config import ShineSettings
from job_market_intel.scrapers.shine.exceptions import (
    ShineError,
    ShineFetchError,
    ShineParseError,
    ShineResponseError,
)
from job_market_intel.scrapers.shine.models import RawShineJob
from job_market_intel.scrapers.shine.parser import (
    ShineParser,
    parse_detail,
)
from job_market_intel.scrapers.shine.pipeline import (
    ShinePipeline,
    ShinePipelineRunResult,
)

__all__ = [
    "ShineClient",
    "ShineError",
    "ShineFetchError",
    "ShineParser",
    "ShinePipeline",
    "ShinePipelineRunResult",
    "ShineResponseError",
    "ShineSettings",
    "RawShineJob",
    "parse_detail",
]
