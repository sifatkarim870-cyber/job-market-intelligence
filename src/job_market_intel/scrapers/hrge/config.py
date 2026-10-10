"""HR.ge-specific configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or timeout change is a one-line ``.env``
edit (prefix ``HRGE_``), not a code change.

HR.ge (Georgia's largest job board) publishes no documented API, but its
Angular frontend talks to a plain JSON API on ``api.p.hr.ge`` (tenant 1 =
hr.ge), discovered in ``assets/conf/api.json`` and confirmed live during
scoping (2026-10-06/07). No API key, no cookies, no signing.

Two site behaviours shaped these defaults:

* **AWS WAF** protects the site (``wafConfig.isEnabled: true``); a
  browser-style User-Agent plus Referer/Accept-Language headers has
  passed every probe request without a challenge.
* **``Accept-Language: en`` returns English content** — employer-provided
  English titles (falling back to Georgian when none exists), fully
  translated taxonomy (specializations, industries, seniority,
  "Full-time"/"Fixed-term contract" enums, city names like "Tbilisi"),
  while descriptions of Georgian-only postings come back as the original
  Georgian text behind a short English notice (stripped by the cleaner).
  So the scraper asks for English and lets the translation layer handle
  whatever still comes back Georgian.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HRGeSettings(BaseSettings):
    """Configuration for the HR.ge scraper, loaded from environment/.env.

    Attributes:
        api_base_url: Public web API base (``public-portal/tenant/1/api/v3/``).
        web_base_url: Public site base; a job's ``/announcement/{id}``
            path is appended to build the canonical ``original_url``.
        page_size: List page size. The server hard-caps ``limit`` at 100
            (``limit=500`` → HTTP 400 "Max 100 items are allowed per
            request"), so 100 is the real page size.
        max_pages_per_run: Safety cap on list pages per run. The live
            site reports ~3,596 active vacancies across ~36 pages of
            100, so the default of 40 covers the whole corpus while
            still bounding one run.
        announcement_type_id: Which announcement type to fetch. Observed
            totals: type 1 (vacancies) = 3,596, type 2 = 0, type 3
            (trainings) = 5. Default 1 keeps the run to actual jobs.
        fetch_details: Whether to call ``announcement/{id}`` for every
            listed job. The list payload has no description, categories
            or seniority; the detail payload has all of them (150
            fields), and descriptions feed skill extraction and the
            word-count quality signal.
        detail_fetch_delay_seconds: Politeness pause between detail
            calls (one run makes up to 40 * 100 of them).
        accept_language: Sent on every request; ``en`` switches the
            site's titles/taxonomy/cities to English (see module
            docstring). Set to ``ka`` via ``HRGE_ACCEPT_LANGUAGE`` to
            fetch raw Georgian instead.
        request_timeout_seconds: Max time to wait for one request.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff.
        user_agent: Browser-style User-Agent — required in practice,
            the AWS WAF challenge treats anything else as a bot.
    """

    model_config = SettingsConfigDict(
        env_prefix="HRGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_base_url: str = "https://api.p.hr.ge/public-portal/tenant/1/api/v3/"
    web_base_url: str = "https://www.hr.ge"
    page_size: int = Field(default=100, ge=1, le=100)
    max_pages_per_run: int = Field(default=40, ge=1)
    max_details_per_run: int = Field(
        default=900,
        ge=0,
        description=(
            "Cap on detail-page requests per run, and therefore the real cost of "
            "one CI pass. The list phase is cheap -- 3,560 ids in 36 seconds -- "
            "but the detail phase is one HTTP request PER POSTING plus a "
            "politeness delay, so a full pass over the 3,560 live postings takes "
            "far longer than the 20-minute CI step and was killed mid-loop with "
            "no progress output at all. "
            "900 fits the budget with headroom, and since pages are fetched "
            "newest-first the budget always covers the newest postings, which are "
            "the ones that change. At the 12-hour cron that is 1,800 "
            "details/day. Raise it for a local full backfill, or set 0 to take "
            "the list entry only."
        ),
    )
    announcement_type_id: int = Field(default=1, ge=1)
    fetch_details: bool = True
    detail_fetch_delay_seconds: float = Field(default=0.1, ge=0.0)
    accept_language: str = "en-US,en;q=0.9"
    request_timeout_seconds: float = 20.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
