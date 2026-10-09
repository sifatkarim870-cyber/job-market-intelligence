"""Greenhouse scraper.

Fetches job postings from Greenhouse's public board API
(``https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true``) and
returns validated, typed ``RawGreenhouseJob`` objects.

Greenhouse is not a job board but an applicant-tracking system that hundreds of
companies run, so there is no single feed -- the endpoint is parameterised by a
board slug. That is what makes this source the highest-leverage free one
available here: a single generic scraper covers an entire company's careers
site, and covering hundreds of companies is a config edit rather than new code.
At the time of writing, four verified boards returned 1,538 postings with full
descriptions between them, all without an API key.

Typical usage:

    from job_market_intel.scrapers.greenhouse import (
        GreenhouseClient, GreenhouseParser, GreenhouseSettings,
    )

    settings = GreenhouseSettings(company_slugs=["gitlab", "stripe"])
    raw_jobs, failures = GreenhouseClient(settings).fetch_all()
    jobs, issues = GreenhouseParser().parse_jobs(raw_jobs)

``failures`` maps slug -> reason. Per-board failures are expected and
non-fatal: a company that moves ATS, or a typo in a slug, should cost one board
rather than the whole run.
"""

from .client import GreenhouseClient
from .config import GreenhouseSettings
from .exceptions import (
    GreenhouseError,
    GreenhouseFetchError,
    GreenhouseParseError,
    GreenhouseResponseError,
)
from .models import RawGreenhouseJob
from .parser import GreenhouseParser
from .pipeline import GreenhousePipeline, GreenhousePipelineRunResult

__all__ = [
    "GreenhouseClient",
    "GreenhouseSettings",
    "GreenhouseError",
    "GreenhouseFetchError",
    "GreenhouseResponseError",
    "GreenhouseParseError",
    "RawGreenhouseJob",
    "GreenhouseParser",
    "GreenhousePipeline",
    "GreenhousePipelineRunResult",
]
