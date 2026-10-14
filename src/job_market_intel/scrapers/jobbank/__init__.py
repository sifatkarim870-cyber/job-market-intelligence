"""Job Bank Canada -- the Government of Canada's official job board.

Why this source exists
----------------------
Canada is a G2 labour market carrying 371 rows (0.3%) in the corpus while Iran
carried 68%. Job Bank is one of very few large national boards that can be read
with a plain HTTP client: no API key, no proxy, no captcha, and its robots.txt
permits the job paths. It also aggregates postings mirrored in from commercial
boards (Talent.com, ZipRecruiter and others), so one walk reaches postings that
would each otherwise need their own scraper.

Typical usage::

    from job_market_intel.scrapers.jobbank import JobBankClient, JobBankParser

    settings = JobBankSettings()
    records, failures = JobBankClient(settings).fetch_raw_jobs()
    jobs, issues = JobBankParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.jobbank.client import JobBankClient
from job_market_intel.scrapers.jobbank.config import JobBankSettings
from job_market_intel.scrapers.jobbank.exceptions import (
    JobBankError,
    JobBankFetchError,
    JobBankParseError,
    JobBankResponseError,
)
from job_market_intel.scrapers.jobbank.models import RawJobBankJob
from job_market_intel.scrapers.jobbank.parser import JobBankParser
from job_market_intel.scrapers.jobbank.pipeline import (
    JobBankPipeline,
    JobBankPipelineRunResult,
)

__all__ = [
    "JobBankClient",
    "JobBankError",
    "JobBankFetchError",
    "JobBankParseError",
    "JobBankPipeline",
    "JobBankPipelineRunResult",
    "JobBankParser",
    "JobBankResponseError",
    "JobBankSettings",
    "RawJobBankJob",
]
