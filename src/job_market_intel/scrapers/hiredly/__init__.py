"""Hiredly (my.hiredly.com) -- a Malaysian job board.

Why this source exists
----------------------
**Malaysia had zero postings in the corpus.** Hiredly is a large Malaysian
board: no key, no registration, no proxy. It was on the "JS-rendered, no
anti-bot" list and re-probed on 2026-10-18, when it was confirmed to be
JS-rendered *and* unwalled -- one of only four boards in that group that
actually are (the other four, keejob / emploipartner / careercenter.am /
jobwebkenya, turned out to be Cloudflare-walled as well and moved to the
"needs a residential IP" list).

The second headless-browser source, and the second ``browser: true`` row in
``config/sources.json``.

Traps, each measured 2026-10-18
-------------------------------
1. **The host must be ``my.hiredly.com``.** ``hiredly.com/jobs/<slug>``
   302s to the homepage -- HTTP 200, a real-looking title, and no posting on
   it. Every single row would have been empty.
2. **Rate limiting hides behind a successful response.** After roughly 60-80
   detail requests inside a few minutes, pages come back HTTP 200 with a good
   title and **no ``#__NEXT_DATA__`` at all**. A burst of 30 with no delay
   returned 30 unusable pages. The client waits for the JSON blob by selector,
   treats its absence as a fetch failure and backs off before retrying.
3. **``__NEXT_DATA__`` and ``ld+json`` disagree.** For one posting the two gave
   different street addresses and postcodes (47300 vs 47400). The ``ld+json``
   block is built from the employer's profile; ``__NEXT_DATA__`` is the
   posting. Only the latter is read.
4. **``props.pageProps.similarJobs`` is a list of other postings**, one level
   below ``job``, each with its own title, company and salary.
5. **``job.salary`` is a display string** -- ``"4000 - 6000"`` or, far more
   often, ``"Undisclosed"``. The figures live in
   ``structuredJobData.baseSalary.value``. The word "Undisclosed" is never
   parsed for digits.
6. **The listing paginates by ``?page=`` only** -- no pager, no "load more".
   30 postings a page, verified distinct across pages 1, 2, 3, 5, 10 and 20.

Compliance
----------
robots.txt: ``User-agent: *`` / ``Allow: /`` -- the whole site is permitted.
"""

from __future__ import annotations

from job_market_intel.scrapers.hiredly.client import HiredlyClient
from job_market_intel.scrapers.hiredly.config import HiredlySettings
from job_market_intel.scrapers.hiredly.exceptions import (
    HiredlyError,
    HiredlyFetchError,
    HiredlyParseError,
    HiredlyResponseError,
)
from job_market_intel.scrapers.hiredly.models import RawHiredlyJob
from job_market_intel.scrapers.hiredly.parser import (
    HiredlyParser,
    extract_job_node,
    extract_next_data,
    parse_salary,
)
from job_market_intel.scrapers.hiredly.pipeline import (
    HiredlyPipeline,
    HiredlyPipelineRunResult,
)

__all__ = [
    "HiredlyCleaner",
    "HiredlyClient",
    "HiredlyError",
    "HiredlyFetchError",
    "HiredlyParseError",
    "HiredlyParser",
    "HiredlyPipeline",
    "HiredlyPipelineRunResult",
    "HiredlyResponseError",
    "HiredlySettings",
    "RawHiredlyJob",
    "extract_job_node",
    "extract_next_data",
    "parse_salary",
]
