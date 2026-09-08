"""We Work Remotely-specific configuration.

Mirrors ``scrapers/remoteok/config.py``'s reasoning exactly: these values
live here, loaded via ``pydantic-settings``, so a change to the feed URL
or a timeout tweak is a one-line ``.env`` edit, not a code change.

Every setting below has a sensible default, so the scraper works
out-of-the-box with no ``.env`` entries at all. Add entries prefixed with
``WWR_`` to your ``.env`` file only when you want to override a default —
for example:

    WWR_REQUEST_TIMEOUT_SECONDS=30
    WWR_MAX_RETRY_ATTEMPTS=6

Note on the ``WWR_`` prefix: shorter than spelling out
``WEWORKREMOTELY_``, and unambiguous — nothing else in this project uses
"WWR" for anything else. Matches the abbreviation We Work Remotely uses
for itself throughout its own site and documentation.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class WWRSettings(BaseSettings):
    """Configuration for the We Work Remotely scraper, loaded from environment/.env.

    Attributes:
        feed_url: We Work Remotely's public "all jobs" RSS feed. WWR also
            publishes 11 category-specific feeds
            (https://weworkremotely.com/remote-job-rss-feed); this
            scraper deliberately starts with just the all-jobs feed
            (matching the project's "complete one thing before expanding"
            principle) and category feeds are a documented future
            enhancement if single-feed volume proves too thin.
        request_timeout_seconds: Max time to wait for WWR to respond to a
            single request before treating it as failed.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: How long to wait before the first
            retry after a transient failure.
        retry_max_wait_seconds: Ceiling on the exponential backoff wait
            time between retries.
        user_agent: Identifying User-Agent string sent with every request.
    """

    model_config = SettingsConfigDict(
        env_prefix="WWR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    feed_url: str = "https://weworkremotely.com/remote-jobs.rss"
    request_timeout_seconds: float = 15.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "JobMarketIntelligencePlatform-Research/1.0 (+https://example-research-project.local)"
    )
