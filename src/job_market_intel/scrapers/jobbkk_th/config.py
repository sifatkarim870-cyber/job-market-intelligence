"""Configuration settings for JobBKK (Thailand) scraper."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class JobbkkSettings(BaseSettings):
    """Runtime configuration for JobBKK scraper."""

    model_config = SettingsConfigDict(
        env_prefix="JOBBKK_TH_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = "https://www.jobbkk.com"
    list_url_template: str = "https://www.jobbkk.com/jobs/lists/{page}"
    max_pages: int = 5
    max_jobs_per_run: int = 60
    request_timeout: float = 15.0
    rate_limit_delay: float = 0.2
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
