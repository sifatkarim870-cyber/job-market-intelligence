"""Configuration settings for JobNet (Myanmar) scraper."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class JobnetSettings(BaseSettings):
    """Runtime configuration for JobNet scraper."""

    model_config = SettingsConfigDict(
        env_prefix="JOBNET_MM_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = "https://www.jobnet.com.mm"
    search_url: str = "https://www.jobnet.com.mm/jobs"
    max_pages: int = 5
    max_jobs_per_run: int = 50
    request_timeout: float = 25.0
    rate_limit_delay: float = 0.5
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
