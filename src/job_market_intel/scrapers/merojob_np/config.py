"""Configuration settings for Merojob (Nepal) scraper."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class MerojobSettings(BaseSettings):
    """Runtime configuration for Merojob scraper."""

    model_config = SettingsConfigDict(
        env_prefix="MEROJOB_NP_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = "https://merojob.com"
    api_base_url: str = "https://api.merojob.com/api/v1"
    jobs_endpoint: str = "https://api.merojob.com/api/v1/jobs/"
    job_detail_endpoint_template: str = "https://api.merojob.com/api/v1/jobs/{job_id}/"

    max_jobs_per_run: int = 60
    request_timeout: float = 15.0
    rate_limit_delay: float = 0.2
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
