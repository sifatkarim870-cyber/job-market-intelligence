"""Configuration for the MojPosao (Croatia) scraper."""
from pydantic_settings import BaseSettings


class MojPosaoHrSettings(BaseSettings):
    """Runtime settings — all overridable via MOJPOSAO_HR_* env vars."""

    base_url: str = "https://www.moj-posao.net"
    search_url: str = "https://www.moj-posao.net/Pretraga-Poslova/"
    max_jobs_per_run: int = 60
    request_timeout: int = 20
    detail_concurrency: int = 5

    model_config = {"env_prefix": "MOJPOSAO_HR_"}
