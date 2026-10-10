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
    # Rows per run, and therefore the real budget.
    #
    # Measured on 2026-10-10 over the CI WAN to Neon: ~1.2 s per detail request
    # plus ~2.04 s per persisted row, so ~3.24 s/row end to end. At that rate the
    # board's 3,560 live postings need about 121 minutes, which no step timeout
    # holds -- not 20 min, and not the workflow's 45.
    #
    # This was the third distinct limit to be discovered on the same run, which
    # is worth stating plainly: a detail-phase deadline was added, then
    # batched commits, and both were correct and neither was sufficient, because
    # the board is simply larger than the step. 7 pages = 700 rows ≈ 38 min.
    #
    # Pages are walked NEWEST-FIRST, so a truncated run always covers the newest
    # postings, which are the only ones that change. The local laptop already
    # holds the full 3,628-row corpus; CI only needs to track turnover, and
    # twice a day at 700 rows is far more than that. A local full backfill
    # restores the old behaviour with HRGE_MAX_PAGES_PER_RUN=40.
    max_pages_per_run: int = Field(default=7, ge=1)
    max_details_per_run: int = Field(
        default=900,
        ge=0,
        description=(
            "HARD cap on detail-page requests per run. "
            "The list phase is cheap -- 3,560 ids in 36 seconds -- but the "
            "detail phase is one HTTP request PER POSTING plus a politeness "
            "delay, so a full pass over the 3,560 live postings takes far "
            "longer than the 20-minute CI step and used to be killed mid-loop "
            "with no progress output at all. "
            "900 leaves room for the rest of the run at the latency measured on "
            "2026-10-10 (1.18 s per detail); the same run showed 900 details "
            "alone consume 17m45s, which is why detail_budget_seconds is the "
            "control that actually matters and this is only a backstop. "
            "Set 0 for list-only."
        ),
    )
    detail_budget_seconds: float = Field(
        default=420.0,
        ge=0.0,
        description=(
            "WALL-CLOCK budget for the detail phase, and the real limit on one CI "
            "pass. A count budget was tried first and was the wrong instrument: "
            "900 details measured 1.18 s each against a Georgian API, four times "
            "the rate assumed, so the phase alone consumed 17m45s of a 20-minute "
            "step and the run was killed before persisting anything. Network "
            "latency varies far more than any constant picked here, so the loop "
            "stops when the clock says so and every posting past that point keeps "
            "its list data -- title, company, location and dates -- missing only "
            "the description and taxonomy. 600s leaves half of a 20-minute step "
            "for cleaning, validation and persistence. Raise it for a local "
            "full-import backfill, or set 0.0 to disable the deadline."
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
