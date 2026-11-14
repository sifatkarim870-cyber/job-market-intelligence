"""Configuration settings for the ADEM (Luxembourg) scraper."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AdemLuSettings(BaseSettings):
    """Configuration for ADEM scraper loaded from environment / defaults."""

    model_config = SettingsConfigDict(env_prefix="ADEM_LU_", extra="ignore")

    base_url: str = Field(
        default="https://adem.public.lu",
        description="Base URL for ADEM Luxembourg portal.",
    )
    endpoint_id: str = Field(
        default="L2NvbnRlbnQvYWRlbTIwMjMvZW4vam9iYm9hcmQvamNyOmNvbnRlbnQvcm9vdC9yb290LXJlc3BvbnNpdmVncmlkL2NvbnRlbnQtcmVzcG9uc2l2ZWdyaWQvc2VjdGlvbnMtcmVzcG9uc2l2ZWdyaWQvc2VjdGlvbl9sb2NhbG5hdi9jb2wxL2pvYmJvYXJk",
        description="AEM component identifier for CTIE JobBoard REST endpoint.",
    )
    request_timeout_seconds: int = Field(default=20, ge=1)
    max_jobs_per_run: int = Field(default=60, ge=1)
    fetch_details: bool = Field(
        default=True,
        description="Whether to fetch individual job descriptions from the offer endpoint.",
    )
    detail_concurrency: int = Field(
        default=5, ge=1, le=10, description="Parallel threads for fetching detail offers."
    )
    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    )
