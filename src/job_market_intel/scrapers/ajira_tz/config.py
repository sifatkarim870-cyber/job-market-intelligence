"""Configuration for the Ajira Tanzania scraper."""
from pydantic_settings import BaseSettings


class AjiraTzSettings(BaseSettings):
    """Runtime settings — all overridable via AJIRA_TZ_* env vars."""

    graphql_url: str = "https://portal.ajira.go.tz/candidates/graphql"
    max_jobs_per_run: int = 200
    request_timeout: int = 20
    # Concurrency for detail fetches
    detail_concurrency: int = 5

    model_config = {"env_prefix": "AJIRA_TZ_"}
