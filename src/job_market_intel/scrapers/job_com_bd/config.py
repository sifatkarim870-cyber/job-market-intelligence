"""Configuration settings for Job.com.bd scraper."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class JobComBdSettings(BaseSettings):
    """Runtime configuration for Job.com.bd scraper."""

    model_config = SettingsConfigDict(
        env_prefix="JOB_COM_BD_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = "https://job.com.bd"
    jobs_url: str = "https://job.com.bd/jobs"
    max_pages: int = 5
    max_jobs_per_run: int = 50
    request_timeout: float = 15.0
    rate_limit_delay: float = 0.2
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
