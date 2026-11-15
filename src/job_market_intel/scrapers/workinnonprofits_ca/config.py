"""Configuration settings for WorkInNonProfits (Canada) scraper."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkInNonProfitsSettings(BaseSettings):
    """Runtime configuration for WorkInNonProfits scraper."""

    model_config = SettingsConfigDict(
        env_prefix="WORKINNONPROFITS_CA_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = "https://workinnonprofits.ca"
    feed_url: str = "https://workinnonprofits.ca/dynamic/job_feed_rss2.xml"
    atom_feed_url: str = "https://workinnonprofits.ca/dynamic/job_feed_atom.xml"
    max_jobs_per_run: int = 50
    request_timeout: float = 15.0
    rate_limit_delay: float = 0.2
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
