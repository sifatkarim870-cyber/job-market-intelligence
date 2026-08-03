"""RemoteOK-specific configuration.

Why these values live here instead of hardcoded in ``client.py``: if
RemoteOK ever changes their API URL, or you need a longer timeout on a slow
network, that should be a one-line change to your ``.env`` file — not a
code change requiring a redeploy. This follows the same
``pydantic-settings`` pattern already used in the rest of the project
(Step 3's configuration loader).

Every setting below has a sensible default, so the scraper works
out-of-the-box with no ``.env`` entries at all. Add entries prefixed with
``REMOTEOK_`` to your ``.env`` file only when you want to override a
default — for example:

    REMOTEOK_REQUEST_TIMEOUT_SECONDS=30
    REMOTEOK_MAX_RETRY_ATTEMPTS=6
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class RemoteOKSettings(BaseSettings):
    """Configuration for the RemoteOK scraper, loaded from environment/.env.

    Attributes:
        api_url: RemoteOK's public JSON job feed.
        request_timeout_seconds: Max time to wait for RemoteOK to respond
            to a single request before treating it as failed.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: How long to wait before the first
            retry after a transient failure.
        retry_max_wait_seconds: Ceiling on the exponential backoff wait
            time between retries.
        user_agent: Identifying User-Agent string sent with every request.
    """

    model_config = SettingsConfigDict(
        env_prefix="REMOTEOK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_url: str = "https://remoteok.com/api"
    request_timeout_seconds: float = 15.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = "JobMarketIntelligencePlatform-Research/1.0 (+https://example-research-project.local)"
