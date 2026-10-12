"""Jobicy scraper.

Fetches remote job postings from Jobicy's public JSON API
(``https://jobicy.com/api/v2/remote-jobs``) and returns validated, typed
``RawJobicyJob`` objects.

Jobicy is a remote-only board with a free, key-free API. It reports a
normalised region (``jobGeo``: USA / UK / Europe / LATAM / APAC) rather than a
city, and controlled vocabularies for seniority and contract type, which map
onto ``ref.experience_levels`` and the employment-type lookup without fuzzy
matching.

Typical usage:

    from job_market_intel.scrapers.jobicy import (
        JobicyClient, JobicyParser, JobicySettings,
    )

    raw_jobs = JobicyClient().fetch_raw_jobs()
    jobs = JobicyParser().parse_jobs(raw_jobs)

Note on identity: ``id`` is the natural key. The API returns it as a number and
the model stringifies it once, at the boundary, so the value logged during
parsing matches the value stored in the text ``core.jobs.source_job_id`` column.

Note on pagination: there is none. ``page`` is rejected with HTTP 400 and
``count`` silently caps at 200, so a run is one request per tag/geo filter.
"""

from .client import JobicyClient
from .config import JobicySettings
from .exceptions import JobicyError, JobicyPermanentError
from .models import RawJobicyJob
from .parser import JobicyParser
from .pipeline import JobicyPipeline, JobicyPipelineRunResult

__all__ = [
    "JobicyClient",
    "JobicyError",
    "JobicyParser",
    "JobicyPermanentError",
    "JobicyPipeline",
    "JobicyPipelineRunResult",
    "JobicySettings",
    "RawJobicyJob",
]
