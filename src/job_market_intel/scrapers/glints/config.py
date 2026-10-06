"""Glints-specific configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or window change is a one-line ``.env``
edit (prefix ``GLINTS_``), not a code change.

Glints (glints.com — Indonesia/Singapore/Vietnam/Malaysia job platform)
has no documented public API for job search: ``/api/v2/jobs`` exists but
returns HTTP 401 ("cookie token is empty") without a logged-in session,
and the GraphQL endpoints require in-session queries discovered per
page. What the site *does* publish is a complete, unauthenticated
sitemap index (``/sitemap_index.xml``, ~376 KB) listing per-country job
sitemaps, each job page server-rendered with its full record embedded
in ``__NEXT_DATA__`` — confirmed live during scoping (2026-10-07). So
this scraper's "API" is sitemap discovery + SSR page parsing; no key,
no cookies, no signing.

Three site behaviours shaped these defaults:

* **Sitemaps carry no ``lastmod``**, but within each country family they
  are ordered newest-created first (``job_id_1`` sampled 2026-10-06
  postings; ``job_id_756`` sampled 2026-08-07). The client walks every
  country family round-robin so a capped run always sees each
  country's freshest postings instead of exhausting Indonesia's 756
  sitemaps first.
* **~130k unique job pages exist** across families (job_id 756 +
  sourced_job_id 546 + vn 55 + sg 4 + my 1 sitemaps, each ~200 URLs
  counting a local/en locale duplicate per job), so a run needs a hard
  window: ``max_jobs_per_run`` caps the *unique jobs* a run will fetch,
  mirroring ``HRGE_MAX_PAGES_PER_RUN``'s role for HR.ge.
* **A polite delay between page fetches** keeps a full-corpus crawl
  (~130k GETs) inside good-neighbor territory; the keep-alive session
  keeps per-request cost to well under a second.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GlintsSettings(BaseSettings):
    """Configuration for the Glints scraper, loaded from environment/.env.

    Attributes:
        web_base_url: Public site base; a job's ``/{cc}/opportunities/…``
            path comes from the sitemap and is stored verbatim as
            ``original_url``.
        sitemap_index_url: The unauthenticated sitemap index that lists
            every per-country job sitemap (``sitemap_job_{cc}_{n}.xml``,
            ``sitemap_sourced_job_{cc}_{n}.xml``).
        max_jobs_per_run: Safety cap on UNIQUE jobs fetched per run.
            The default of 400 mirrors HR.ge's CI window (4 pages x 100)
            — CI catches whatever posted since the last run; the local
            full backfill raises it via ``GLINTS_MAX_JOBS_PER_RUN``.
        fetch_delay_seconds: Politeness pause between job-page fetches
            (a full-corpus crawl makes ~130k of them).
        request_timeout_seconds: Max time to wait for one request.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff.
        user_agent: Browser-style User-Agent; Glints serves its SSR
            pages fine to one, and identifying honestly is the polite
            thing to do regardless.
    """

    model_config = SettingsConfigDict(
        env_prefix="GLINTS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    web_base_url: str = "https://glints.com"
    sitemap_index_url: str = "https://glints.com/sitemap_index.xml"
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
