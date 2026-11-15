"""Configuration settings for Jobkorea scraper."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class JobkoreaSettings(BaseSettings):
    """Runtime configuration for Jobkorea scraper."""

    model_config = SettingsConfigDict(
        env_prefix="JOBKOREA_KR_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = "https://www.jobkorea.co.kr"
    list_url: str = "https://www.jobkorea.co.kr/recruit/joblist"
    max_pages: int = 5
    max_jobs_per_run: int = 50
    request_timeout: float = 25.0
    rate_limit_delay: float = 0.5
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
