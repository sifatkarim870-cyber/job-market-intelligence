"""Configuration for the FINN.no (Norway) scraper."""
from pydantic_settings import BaseSettings


class FinnNoSettings(BaseSettings):
    """Runtime settings — all overridable via FINN_NO_* env vars."""

    base_url: str = "https://www.finn.no"
    search_url: str = "https://www.finn.no/job/search"
    max_jobs_per_run: int = 60
    request_timeout: int = 20
    detail_concurrency: int = 5

    model_config = {"env_prefix": "FINN_NO_"}
