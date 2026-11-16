"""Configuration settings for Gallito (Uruguay) scraper."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class GallitoSettings(BaseSettings):
    """Runtime configuration for Gallito scraper."""

    model_config = SettingsConfigDict(
        env_prefix="GALLITO_UY_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = "https://trabajo.gallito.com.uy"
    search_url: str = "https://trabajo.gallito.com.uy/buscar"
    max_pages: int = 5
    max_jobs_per_run: int = 50
    request_timeout: float = 25.0
    rate_limit_delay: float = 0.5
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
