"""JobsNepal (jobsnepal.com) -- a Nepali job board.

Why this source exists
----------------------
Nepal had **no** postings in the corpus. JobsNepal needs no key, no registration
and no proxy, and paginates: ``/top-job`` carries ~12 postings and
``/top-job?page=2`` adds 8 new ones.

No structured data
------------------
No schema.org JSON-LD. Everything is markup extraction from labelled rows::

    Job posted on 05 Oct, 2026 Apply before 18 Oct, 2026
    LOCATION Central Office
    Salary: Negotiable as per competence and experience.
    Position Type Full Time
    Experience 7+ years
    Category Accounting/Finance
    Posted Date 05 Oct, 2026

The ``<title>`` is ``"<Job Title> - <Company> - <id> - JobsNepal"``, which is
where the company comes from -- there is no labelled company field.

``Salary`` reads ``"Negotiable as per competence and experience."`` -- prose, not
a figure, so no salary is stored. The verbatim string is kept in
``raw_payload[\"salary_text\"]``.

Compliance
----------
robots.txt: ``User-agent: *`` with an empty ``Disallow:`` -- the whole site is
permitted.

Typical usage::

    from job_market_intel.scrapers.jobsnepal import JobsNepalClient, JobsNepalParser

    records, failures = JobsNepalClient().fetch_raw_jobs()
    jobs, issues = JobsNepalParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.jobsnepal.client import JobsNepalClient
from job_market_intel.scrapers.jobsnepal.config import JobsNepalSettings
from job_market_intel.scrapers.jobsnepal.exceptions import (
    JobsNepalError,
    JobsNepalFetchError,
    JobsNepalParseError,
    JobsNepalResponseError,
)
from job_market_intel.scrapers.jobsnepal.models import RawJobsNepalJob
from job_market_intel.scrapers.jobsnepal.parser import JobsNepalParser, parse_detail
from job_market_intel.scrapers.jobsnepal.pipeline import (
    JobsNepalPipeline,
    JobsNepalPipelineRunResult,
)

__all__ = [
    "JobsNepalCleaner",
    "JobsNepalClient",
    "JobsNepalError",
    "JobsNepalFetchError",
    "JobsNepalParseError",
    "JobsNepalParser",
    "JobsNepalPipeline",
    "JobsNepalPipelineRunResult",
    "JobsNepalResponseError",
    "JobsNepalSettings",
    "RawJobsNepalJob",
    "parse_detail",
]
