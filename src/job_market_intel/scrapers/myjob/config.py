"""MyJob.mu-specific configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or timeout change is a one-line ``.env``
edit (prefix ``MYJOB_``), not a code change.

No API key needed (MyJob.mu's job-board JSON endpoints answer without
auth, confirmed live 2026-10-05), so ``api_key`` does not exist here —
everything has a sensible default and the scraper works out of the box.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MyJobSettings(BaseSettings):
    """Configuration for the MyJob.mu scraper, loaded from environment/.env.

    Attributes:
        api_base_url: The job-board JSON list endpoint. Query parameters
            (``?limit=&sort=&page=``) are appended by the client.
        web_base_url: The public listing-page base; a job's ``slug`` is
            appended to build the canonical ``original_url`` (the page a
            human would visit), not the API URL.
        page_size: Jobs per list page. The server silently caps ``limit``
            at 20 (a ``limit=1000`` request still returns 20), so 20 is
            the real page size regardless of what is requested.
        max_pages_per_run: Safety cap on how many list pages one run
            fetches (20 jobs per page). The live site reports ~1,500
            openings across ~75 pages; a cap keeps one pipeline run
            bounded and polite. Raise via ``MYJOB_MAX_PAGES_PER_RUN``.
        fetch_details: Whether to call the detail endpoint
            (``/jobs/{id}``) for every listed job. The list payload has
            no ``description``; the detail payload does, and descriptions
            feed skill extraction and the word-count quality signal.
            Setting this to False trades descriptions away for speed.
        detail_fetch_delay_seconds: Politeness pause between detail
            calls (one run makes up to ``max_pages_per_run * 20`` of
            them). 0 for no delay.
        request_timeout_seconds: Max time to wait for one request.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff (also the
            effective cooldown after a 429).
        user_agent: Identifying User-Agent sent with every request.
    """

    model_config = SettingsConfigDict(
        env_prefix="MYJOB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_base_url: str = "https://app.myjob.mu/api/job-board/jobs"
    web_base_url: str = "https://www.myjob.mu/jobs"
    page_size: int = Field(default=20, ge=1, le=20)
    max_pages_per_run: int = Field(default=5, ge=1)
    fetch_details: bool = True
    detail_fetch_delay_seconds: float = Field(default=0.5, ge=0.0)
    request_timeout_seconds: float = 20.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "JobMarketIntelligencePlatform-Research/1.0 (+https://example-research-project.local)"
    )
