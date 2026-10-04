"""Emploitic scraper.

Fetches job listings from Emploitic (https://emploitic.com), Algeria's
largest job board, validated, typed ``RawEmploiticJob`` objects.

Emploitic has no public documented JSON API; its Next.js frontend server-
renders the full job-search result as a JSON payload inside the page's
``__NEXT_DATA__`` script tag (``props.pageProps.searchResult``). This
scraper fetches those listing pages (one HTTP GET per page), extracts that
JSON, and returns typed objects — the closest thing to the free JSON API
the source offers, confirmed live during scoping (2026-10-04).

Typical usage:

    from job_market_intel.scrapers.emploitic import EmploiticClient, EmploiticParser, EmploiticSettings

    settings = EmploiticSettings()
    client = EmploiticClient(settings=settings)
    parser = EmploiticParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import EmploiticClient
from .config import EmploiticSettings
from .exceptions import EmploiticError, EmploiticFetchError, EmploiticResponseError
from .models import RawEmploiticJob
from .parser import EmploiticParser
from .pipeline import EmploiticPipeline, EmploiticPipelineRunResult

__all__ = [
    "EmploiticClient",
    "EmploiticSettings",
    "EmploiticError",
    "EmploiticFetchError",
    "EmploiticResponseError",
    "RawEmploiticJob",
    "EmploiticParser",
    "EmploiticPipeline",
    "EmploiticPipelineRunResult",
]
