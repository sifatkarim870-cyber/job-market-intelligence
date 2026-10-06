"""Jobinja-specific configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or window change is a one-line ``.env``
edit (prefix ``JOBINGJA_``), not a code change.

Jobinja (jobinja.ir — Iran) has no public JSON API for job search: the
``/api/v10/*`` routes found in the site bundle are auth-only resume/
notification endpoints (bundle-mined 2026-10-07), and there are no
sitemaps (``/sitemap.xml`` → 404). What the site *does* serve in the
open is a server-rendered listing (``/jobs?page=N`` — 20 cards per
page, newest-first, zero overlap between pages) and per-job pages whose
full record is embedded as schema.org JSON-LD ``JobPosting`` (6/6
sampled pages) plus ``<h4>…</h4><div class="tags">`` metadata sections.
Confirmed live during scoping (2026-10-07). So this scraper's "API"
is listing pagination + JSON-LD/section parsing; no key, no cookies.

Three site behaviours shaped these defaults:

* **Listing pagination is the only discovery channel** — pages are
  strictly newest-first (page 1 sampled 2026-10-06, page 421
  2026-08-27, page 842 2026-08-08; page 843 empty), so ``start_page=1``
  is always "the newest window", and a backfill walks deeper by raising
  ``JOBINGJA_START_PAGE`` instead of needing an exclusion set (the
  scrape still relies on content-hash dedup at persist time).
* **Detail pages are small** (≈120 KB vs Glints' 300–500 KB) but still
  cost a full request each: 400 jobs ≈ 20 listing fetches + 400 detail
  fetches at the politeness delay below.
* **The window bounds one run's in-memory batch** (raw HTML + parsed +
  cleaned), same as every other source — chunked local backfills raise
  it, CI keeps the default.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobinjaSettings(BaseSettings):
    """Configuration for the Jobinja scraper, loaded from environment/.env.

    Attributes:
        web_base_url: Public site base; a job's ``/companies/{co}/jobs/
          {code}/{slug}`` path comes from the listing and is stored
          verbatim as ``original_url``.
        listing_url_template: Paginated listing URL; ``{page}`` is
          substituted with the page number (1-based).
        start_page: First listing page to read. CI always wants 1 (the
          newest window); a chunked local backfill raises it to walk
          deeper into the corpus.
        max_jobs_per_run: Safety cap on unique job pages fetched per
            run. The default of 400 mirrors the other CI windows — CI
            catches whatever posted since the last run; a local
            backfill raises it via ``JOBINGJA_MAX_JOBS_PER_RUN``.
        fetch_delay_seconds: Politeness pause between detail fetches.
        request_timeout_seconds: Max time to wait for one request.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff.
        user_agent: Browser-style User-Agent; Jobinja serves its SSR
            pages fine to one, and identifying honestly is the polite
            thing to do regardless.
    """

    model_config = SettingsConfigDict(
        env_prefix="JOBINGJA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    web_base_url: str = "https://jobinja.ir"
    listing_url_template: str = "https://jobinja.ir/jobs?page={page}"
    start_page: int = Field(default=1, ge=1)
    max_jobs_per_run: int = Field(default=400, ge=1)
    fetch_delay_seconds: float = Field(default=0.15, ge=0.0)
    request_timeout_seconds: float = 25.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
