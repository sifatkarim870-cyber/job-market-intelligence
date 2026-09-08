"""We Work Remotely scraper.

Fetches job listings from We Work Remotely's public RSS feed
(``https://weworkremotely.com/remote-jobs.rss``) and returns validated,
typed ``RawWWRJob`` objects.

Mirrors ``scrapers.remoteok``'s package boundary exactly: this package
does NOT clean, normalize, or store data — see that package's docstring
for why that boundary matters. The structural differences worth knowing
up front (confirmed by fetching the live feed directly, not assumed):
We Work Remotely's feed is RSS/XML, not JSON; it has no numeric
per-posting ID (``source_job_id`` is derived from the job URL's slug,
see ``models.py``); it combines company and job title into a single
``"Company: Job Title"`` string (split in ``models.py``); and it has no
structured salary field at all. See ``models.py``'s module docstring for
the complete list.

Typical usage:

    from job_market_intel.scrapers.weworkremotely import WWRClient, WWRParser, WWRSettings

    settings = WWRSettings()
    client = WWRClient(settings=settings)
    parser = WWRParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import WWRClient
from .config import WWRSettings
from .exceptions import WWRError, WWRFetchError, WWRResponseError
from .models import RawWWRJob
from .parser import WWRParser
from .pipeline import WWRPipeline, WWRPipelineRunResult

__all__ = [
    "WWRClient",
    "WWRSettings",
    "WWRError",
    "WWRFetchError",
    "WWRResponseError",
    "RawWWRJob",
    "WWRParser",
    "WWRPipeline",
    "WWRPipelineRunResult",
]
