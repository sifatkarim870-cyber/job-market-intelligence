"""Emploitic-specific configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or timeout change is a one-line ``.env``
edit (prefix ``EMPLOITIC_``), not a code change.

No API key needed (Emploitic exposes its search results without auth), so
``api_key`` does not exist here — unlike ``ReedSettings``, everything has
a sensible default and the scraper works out of the box.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmploiticSettings(BaseSettings):
    """Configuration for the Emploitic scraper, loaded from environment/.env.

    Attributes:
        base_url: The job-listing landing page. The per-page query
            parameter (``?page=N``, 1-based) is appended by the client.
        max_pages_per_run: Safety cap on how many listing pages one run
            fetches (20 jobs per page). The live site reports thousands of
            openings across hundreds of pages; a cap keeps one pipeline run
            bounded and polite. Raise via ``EMPLOITIC_MAX_PAGES_PER_RUN``.
        request_timeout_seconds: Max time to wait for one page.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff (also the
            effective cooldown after a 429).
        user_agent: Identifying User-Agent sent with every request.
    """

    model_config = SettingsConfigDict(
        env_prefix="EMPLOITIC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_url: str = "https://emploitic.com/offres-d-emploi"
    max_pages_per_run: int = Field(default=5, ge=1)
    request_timeout_seconds: float = 20.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "JobMarketIntelligencePlatform-Research/1.0 (+https://example-research-project.local)"
    )
