"""XpressJobs-specific configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or window change is a one-line ``.env``
edit (prefix ``XPRESS_JOBS_``), not a code change.

What XpressJobs is (``xpress.jobs``, Sri Lanka's general job board)
------------------------------------------------------------------
The site is a React single-page app served by ``nginx`` with no
Cloudflare and no bot wall, but its HTML shell is an empty 1.8 KB
``<div id="root">`` -- the jobs are loaded by JavaScript from a keyless
public JSON API under ``/api/``. Two GETs on that API carry everything
this source needs, both confirmed live during scoping (2026-11-28):

* **Listing** - ``GET https://xpress.jobs/api/jobs/searchJobs`` answers a
  **bare JSON array** (not an envelope) of listing rows with ``page``
  (1-based), ``pageSize`` (ceilings at 100 server-side) and
  ``sortBy=SortedCreateDate DESC``. The public search page's own sort
  control uses exactly three values -- ``NEWID()`` (Default, random),
  ``SortedCreateDate DESC`` (Recent) and ``SortedCreateDate ASC`` (Old) --
  and the recent value is the one that makes the feed deterministic and
  newest-first, so pagination by ``page`` is stable. Every row carries
  ``recordCount`` (the board's live total; 4,143 on 2026-11-28).
* **Detail** - ``GET https://xpress.jobs/api/jobs/publishedJob?jobId=<id>``
  returns the full ad: ``jobInfo`` (HTML body), ``education``,
  ``experience``, ``minSalary``/``maxSalary``/``salaryRange``,
  ``sectors``, the nested ``jobItem`` (the listing row again) and the
  ``organization`` record.

The public ad URL is ``https://xpress.jobs/jobs/view/<jobId>`` (HTTP 200;
the site appends a slug that is not needed for the URL to resolve).

robots.txt posture
------------------
``https://xpress.jobs/robots.txt`` answers HTTP 200, 114 bytes, with a
single generic group: ``User-agent: *`` followed by an **empty**
``Disallow:`` directive and a ``Sitemap:`` line. An empty ``Disallow:``
means "disallow nothing", so the whole site -- ``/api/jobs/searchJobs``
and the ad pages alike -- is allowed, and there is no ``Crawl-delay``.
No key, no registration, no cookie, no proxy; TLS verification stays on.

Two data facts shaped these defaults:

* **Salary is usually not stated.** Most ads answer ``minSalary``/
  ``maxSalary`` with the literal string ``"Any"``, and the board writes a
  placeholder ``"1"`` bound when it hides a figure. The cleaner treats
  both as undisclosed (see ``cleaning/xpress_jobs_cleaner.py``) rather
  than storing a 1-LKR salary.
* **``fetch_delay_seconds`` defaults to 0.2** -- one detail request is
  made per job, so a 200-row run is ~202 requests; a short pause keeps the
  sweep polite without meaningfully lengthening it.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class XpressJobsSettings(BaseSettings):
    """Configuration for the XpressJobs scraper, loaded from environment/.env.

    Attributes:
        search_url: The open listing endpoint; page/pageSize/sortBy ride in
            the query string and the response is a bare JSON array.
        detail_url: The open detail endpoint, keyed by ``jobId``.
        web_base_url: Public site base, used to build the reader-facing
            ``original_url`` and the request ``Origin``/``Referer``.
        sort_by: The listing sort expression. ``"SortedCreateDate DESC"``
            is the public page's "Recent" option and the only setting that
            makes the feed deterministic - the default ``NEWID()`` is
            random per call and cannot be paged.
        start_page: First listing page to read (1-based, newest-first).
            CI always wants 1; a chunked backfill raises it to walk older
            pages.
        page_size: Rows requested per listing page. The API caps this at
            100 server-side (larger values are silently truncated), so 100
            is the largest useful request.
        max_jobs_per_run: Safety cap on jobs fetched per run. One detail
            request is made per job, so the default of 200 is ~2 listing
            pages plus 200 detail GETs. A local backfill raises it via
            ``XPRESS_JOBS_MAX_JOBS_PER_RUN``.
        fetch_delay_seconds: Politeness pause between detail GETs.
        request_timeout_seconds: Max time to wait for one request.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff.
        user_agent: Browser-style User-Agent; the endpoints serve fine to
            one, and identifying honestly is polite regardless.
    """

    model_config = SettingsConfigDict(
        env_prefix="XPRESS_JOBS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    search_url: str = "https://xpress.jobs/api/jobs/searchJobs"
    detail_url: str = "https://xpress.jobs/api/jobs/publishedJob"
    web_base_url: str = "https://xpress.jobs"
    sort_by: str = "SortedCreateDate DESC"
    start_page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=100)
    max_jobs_per_run: int = Field(default=200, ge=1)
    fetch_delay_seconds: float = Field(default=0.2, ge=0.0)
    request_timeout_seconds: float = 40.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
