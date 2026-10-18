"""JobSearch.az (jobsearch.az) -- an Azerbaijani job board.

Why this source exists
----------------------
Azerbaijan had **no** postings in the corpus. JobSearch.az is the largest
Azerbaijani job board: no key, no registration, no proxy.

The first headless-browser source in this project
-------------------------------------------------
The site is a **Nuxt SPA**. Plain HTTP returns 512 KB of bundle with zero
anchors -- the same symptom that made the workbook's "HTML scraper" verdict
wrong for keejob.com, hiredly.com and shine.com. A headless Chromium (Playwright,
a declared dependency) renders the listing and exposes 30 cards shaped
``/vacancies/<slug>``. A "Daha ətraflı" ("Load more") button loads more.

``playwright`` is declared in ``pyproject.toml`` (not ad-hoc installed) and
``playwright install chromium`` is required in CI -- see the workflow note.

Traps, each measured 2026-10-18
-------------------------------
1. **The first ``<h1>`` is the company, not the job.** The company block renders
   above the vacancy block, so ``soup.h1`` is ``Amper Elektrik``. Only
   ``h1.vacancy__title`` is the job title and only ``h1.company__title`` is the
   employer.
2. **The posting date is year-less and lives only on the listing card**:
   "Bu gün" (today), "Dünən" (yesterday), "16 okt" (16 October, no year). The
   year is inferred and rolled back when it would land in the future.
3. **The deadline is in Azerbaijani.** "Son tarix 16 noy 2026" means
   "Deadline 16 Nov 2026".
4. **There is no salary.** Every card renders a ``li.money``, but the figure is
   injected after the DOM snapshot and reads empty.
5. **Whole-page text is 5,849 characters of navigation chrome** against a
   2,488-character description in ``#content_block``.

Compliance
----------
robots.txt: ``User-agent: *`` / ``Allow: /`` -- the whole site is permitted.
"""

from __future__ import annotations

from job_market_intel.scrapers.jobsearch_az.client import JobSearchAzClient
from job_market_intel.scrapers.jobsearch_az.config import JobSearchAzSettings
from job_market_intel.scrapers.jobsearch_az.exceptions import (
    JobSearchAzError,
    JobSearchAzFetchError,
    JobSearchAzParseError,
    JobSearchAzResponseError,
)
from job_market_intel.scrapers.jobsearch_az.models import RawJobSearchAzJob
from job_market_intel.scrapers.jobsearch_az.parser import (
    JobSearchAzParser,
    parse_deadline,
    parse_posted_label,
)
from job_market_intel.scrapers.jobsearch_az.pipeline import (
    JobSearchAzPipeline,
    JobSearchAzPipelineRunResult,
)

__all__ = [
    "JobSearchAzCleaner",
    "JobSearchAzClient",
    "JobSearchAzError",
    "JobSearchAzFetchError",
    "JobSearchAzParseError",
    "JobSearchAzParser",
    "JobSearchAzPipeline",
    "JobSearchAzPipelineRunResult",
    "JobSearchAzResponseError",
    "JobSearchAzSettings",
    "RawJobSearchAzJob",
    "parse_deadline",
    "parse_posted_label",
]
