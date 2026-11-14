"""Configuration for the Vrabotuvanje (North Macedonia) scraper."""
from pydantic_settings import BaseSettings


class VrabotuvanjeMkSettings(BaseSettings):
    """Runtime settings — all overridable via VRABOTUVANJE_MK_* env vars."""

    base_url: str = "https://www.vrabotuvanje.com.mk"
    jobs_url: str = "https://www.vrabotuvanje.com.mk/rabotni-mesta"
    max_jobs_per_run: int = 60
    request_timeout: int = 20
    detail_concurrency: int = 5

    model_config = {"env_prefix": "VRABOTUVANJE_MK_"}
