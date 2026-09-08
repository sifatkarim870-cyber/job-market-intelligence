"""Remotive-specific configuration.

Mirrors ``scrapers/remoteok/config.py``/``scrapers/weworkremotely/config.py``'s
reasoning exactly: these values live here, loaded via ``pydantic-settings``,
so a change to the API URL or a timeout tweak is a one-line ``.env`` edit,
not a code change.

Every setting below has a sensible default, so the scraper works
out-of-the-box with no ``.env`` entries at all. Add entries prefixed with
``REMOTIVE_`` to your ``.env`` file only when you want to override a
default — for example:

    REMOTIVE_REQUEST_TIMEOUT_SECONDS=30
    REMOTIVE_MAX_RETRY_ATTEMPTS=6

Note on ``api_url``: ``https://remotive.com/api/remote-jobs`` — the
``remotive.io`` domain used in some older third-party writeups is retired.
Confirmed directly against the official ``remotive-com/remote-jobs-api``
GitHub README while investigating Step 18, not assumed.

Note on ``max_requests_per_day``: Remotive's own published guidance asks
API consumers to stay at or below 4 requests per day (harder-blocking
above roughly 2 requests per minute). This project's existing 12-hour
APScheduler interval (Step 12) already calls this endpoint only twice a
day, well inside that budget, so no scheduling change is needed for
Remotive specifically — this setting exists as a documented, checkable
ceiling for anyone tuning the schedule later, not because current
behavior is at risk of breaching it.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class RemotiveSettings(BaseSettings):
    """Configuration for the Remotive scraper, loaded from environment/.env.

    Attributes:
        api_url: Remotive's public JSON API endpoint. Returns every
            currently-active listing in one response (optionally capped
            via a ``limit`` query parameter, not used here since a full
            scrape wants everything) — no pagination to manage, same
            "single feed" shape as We Work Remotely's RSS.
        request_timeout_seconds: Max time to wait for Remotive to respond
            to a single request before treating it as failed.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: How long to wait before the first
            retry after a transient failure.
        retry_max_wait_seconds: Ceiling on the exponential backoff wait
            time between retries.
        user_agent: Identifying User-Agent string sent with every request.
        max_requests_per_day: Documented ceiling from Remotive's own API
            guidance. Not enforced in code at this step (the 12-hour
            scheduler interval already respects it) — kept here as an
            explicit, checkable constant rather than a fact that only
            lives in a code comment.
    """

    model_config = SettingsConfigDict(
        env_prefix="REMOTIVE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_url: str = "https://remotive.com/api/remote-jobs"
    request_timeout_seconds: float = 15.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "JobMarketIntelligencePlatform-Research/1.0 (+https://example-research-project.local)"
    )
    max_requests_per_day: int = 4
