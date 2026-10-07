"""Irantalent-specific configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or window change is a one-line ``.env``
edit (prefix ``IRANTALENT_``), not a code change.

IranTalent (irantalent.com — "ایران تلنت", an Iranian job platform)
exposes exactly one unauthenticated JSON endpoint, fully mapped during
scoping (2026-10-07, probes r1-r10):

* **``POST https://api.irantalent.com/api/v1/employer/position/search``
  with body ``{"page": N}``** returns a Laravel paginator envelope
  (``current_page``, ``data``, ``total``, ``last_page``, …) whose
  ``data`` rows carry the COMPLETE job record inline — title,
  ``title_farsi``, HTML ``role_description``, ``salary_from/to``,
  ``employment_type``, ``employer``, ``job_category``, ``lived_at`` —
  so there is no detail endpoint to call (the site's own pages are
  4.4 KB SPA shells; discovery and data are the same request).
* **Pagination facts**: ``per_page`` is fixed at 30 (the ``size``/
  ``per_page`` body params are ignored), rows are ordered
  newest-first by ``lived_at``/id (stable cursor: page 1 = yesterday,
  page 63 = the oldest live jobs), and past the end the API returns
  HTTP 200 with ``data: []`` (verified at page 64). ``total`` was
  1,872 live jobs at scoping — the whole corpus fits a single
  ``max_jobs_per_run`` of ~2,000 (67 pages).
* **Headers**: only a browser ``User-Agent`` and
  ``Content-Type: application/json`` are needed — no Referer, no
  token, no cookie (bare-header probe passed).

Two data facts shaped these defaults:

* **Salary bounds are whole Toman** (observed 200,000,000 ..
  1,700,000,000 monthly — unlike Jobvision's *millions of* Toman),
  gated by ``is_show_salary``; the raw model keeps source units and
  ``cleaning/irantalent_cleaner.py`` applies the ≤0/reversal/withhold
  rules. Currency ``IRT`` is pending the user's
  ``_USD_CONVERSION_RATES`` decision (no IRT rate yet ⇒ NULL, non-fatal).
* **``fetch_delay_seconds`` defaults to 0.25** — the same morning's
  Jobinja WAF challenge (unpaced listing bursts) was a reminder that
  the polite default is load-bearing; a full-corpus sweep is only 63
  page POSTs, so 0.25 s costs under a minute.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IrantalentSettings(BaseSettings):
    """Configuration for the Irantalent scraper, loaded from environment/.env.

    Attributes:
        api_search_url: The open POST search endpoint; the client
            appends nothing — the page number rides in the JSON body.
        web_base_url: Public site base; the client constructs each
            job's ``/{en|fa}/job/{slug}/{id}`` URL from the record's
            own ``slug``/``id``/``language`` (the API gives no URL;
            ``redirection_url`` is null on every sampled row).
        start_page: First search page to read (1-based, newest-first).
            CI always wants 1; a chunked backfill raises it to walk
            older pages.
        max_jobs_per_run: Safety cap on rows fetched per run. The
            default of 400 mirrors the other CI windows; a local full
            backfill raises it via ``IRANTALENT_MAX_JOBS_PER_RUN`` (the
            entire ~1,872-job live corpus fits in one 2,000 window).
        fetch_delay_seconds: Politeness pause between search page
            POSTs (~450 KB each).
        request_timeout_seconds: Max time to wait for one request.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff.
        user_agent: Browser-style User-Agent; the endpoint serves fine
            to one, and identifying honestly is polite regardless.
    """

    model_config = SettingsConfigDict(
        env_prefix="IRANTALENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_search_url: str = "https://api.irantalent.com/api/v1/employer/position/search"
    web_base_url: str = "https://www.irantalent.com"
    start_page: int = Field(default=1, ge=1)
    max_jobs_per_run: int = Field(default=400, ge=1)
    fetch_delay_seconds: float = Field(default=0.25, ge=0.0)
    request_timeout_seconds: float = 40.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
