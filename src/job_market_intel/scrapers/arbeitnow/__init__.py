"""Arbeitnow scraper.

Fetches job postings from Arbeitnow's public JSON API
(``https://www.arbeitnow.com/api/job-board-api``) and returns validated, typed
``RawArbeitnowJob`` objects.

Arbeitnow is a German job board covering Germany, Austria, Switzerland, the
Netherlands and the UK. The API returns the whole active listing in one
response -- no pagination -- and needs no key.

Typical usage:

    from job_market_intel.scrapers.arbeitnow import (
        ArbeitnowClient, ArbeitnowParser, ArbeitnowSettings,
    )

    raw_jobs = ArbeitnowClient().fetch_raw_jobs()
    jobs, issues = ArbeitnowParser().parse_jobs(raw_jobs)

Note on identity: this API has no numeric id. The natural key is ``slug``, a
human-readable per-job string that is stable for the life of the posting, and
that is what ``source_job_id`` is aliased from.
"""

from .client import ArbeitnowClient
from .config import ArbeitnowSettings
from .exceptions import (
    ArbeitnowError,
    ArbeitnowFetchError,
    ArbeitnowParseError,
    ArbeitnowResponseError,
)
from .models import RawArbeitnowJob
from .parser import ArbeitnowParser
from .pipeline import ArbeitnowPipeline, ArbeitnowPipelineRunResult

__all__ = [
    "ArbeitnowClient",
    "ArbeitnowSettings",
    "ArbeitnowError",
    "ArbeitnowFetchError",
    "ArbeitnowResponseError",
    "ArbeitnowParseError",
    "RawArbeitnowJob",
    "ArbeitnowParser",
    "ArbeitnowPipeline",
    "ArbeitnowPipelineRunResult",
]
