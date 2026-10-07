"""Irantalent scraper.

Fetches job listings from IranTalent (https://irantalent.com — "ایران
تلنت", an Iranian job platform), validated into typed
``RawIrantalentJob`` objects.

Discovery and data are the same request: an unauthenticated
``POST api.irantalent.com/api/v1/employer/position/search`` paginator
(body ``{"page": N}``) returns complete job rows inline (30 per page,
newest-first stable cursor, ``per_page`` fixed; empty ``data`` list past
the end) — the site's own pages are data-less SPA shells, so no detail
endpoint exists or is needed. Content is Persian-majority (``fa``/
``multi``/``en`` rows); titles are translated by CI before
classification, descriptions by the local NLLB batch.

Typical usage:

    from job_market_intel.scrapers.irantalent import (
        IrantalentClient, IrantalentParser, IrantalentSettings,
    )

    settings = IrantalentSettings()
    client = IrantalentClient(settings=settings)
    parser = IrantalentParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import IrantalentClient
from .config import IrantalentSettings
from .exceptions import IrantalentError, IrantalentFetchError, IrantalentResponseError
from .models import RawIrantalentJob
from .parser import IrantalentParser
from .pipeline import IrantalentPipeline, IrantalentPipelineRunResult

__all__ = [
    "IrantalentClient",
    "IrantalentSettings",
    "IrantalentError",
    "IrantalentFetchError",
    "IrantalentResponseError",
    "RawIrantalentJob",
    "IrantalentParser",
    "IrantalentPipeline",
    "IrantalentPipelineRunResult",
]
