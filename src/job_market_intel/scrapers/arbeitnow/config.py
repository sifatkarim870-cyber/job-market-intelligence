"""Arbeitnow-specific configuration.

Arbeitnow is a German job board with a public JSON API and no key requirement.
It is Europe-focused (Germany, Austria, Switzerland, Netherlands, UK) and
returns the full description as HTML, which makes it a good complement to the
US/UK-heavy sources already in the corpus.

Every setting has a working default, so the scraper runs with no .env entries.
Override with ``ARBEITNOW_`` prefixes, e.g.:

    ARBEITNOW_REQUEST_TIMEOUT_SECONDS=30
    ARBEITNOW_MAX_JOBS_PER_RUN=500
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ArbeitnowSettings(BaseSettings):
    """Configuration for the Arbeitnow scraper, loaded from environment/.env."""

    model_config = SettingsConfigDict(env_prefix="ARBEITNOW_", extra="ignore")

    api_url: str = Field(
        default="https://www.arbeitnow.com/api/job-board-api",
        description="Arbeitnow's public job board API. Returns the whole active "
        "listing in one response -- no pagination to manage.",
    )
    request_timeout_seconds: int = Field(default=25, ge=1)
    max_jobs_per_run: int = Field(default=1000, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=1.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=8.0, ge=0.0)
    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    )
