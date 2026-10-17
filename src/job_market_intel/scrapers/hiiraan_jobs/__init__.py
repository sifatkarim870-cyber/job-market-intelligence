"""Hiiraan jobs (hiiraan.com) -- a Somali job board.

Why this source exists
----------------------
Somalia had **no** postings in the corpus. Hiiraan is a Somali news portal's
job section: no key, no registration, no proxy, and it lists 16 postings as PDF
Terms of Reference.

PDF, not HTML
-------------
This is the first source in this project whose detail pages are **PDFs** rather
than HTML. Text is extracted with ``pypdf`` (a declared dependency in
``pyproject.toml``, not an ad-hoc install -- the lxml lesson). The PDFs are
well-structured Terms of Reference with labelled fields::

    Position Title: Full-Stack Software Engineer
    Department: Information Technology
    Position Level: Level 1 Officer
    Reports To: Head of Information Technology
    Employment Type: Full-time
    Location: Mogadishu, Somalia
    Deadline for submission: 17th August 2026, 11.59 PM Mogadishu time.

No salary, no posting date, no company field. The employer is the organization
named in the background prose, which is not a field, so ``company_name`` stays
"Unknown employer".

Typical usage::

    from job_market_intel.scrapers.hiiraan_jobs import HiiraanJobsClient, HiiraanJobsParser

    records, failures = HiiraanJobsClient().fetch_raw_jobs()
    jobs, issues = HiiraanJobsParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.hiiraan_jobs.client import HiiraanJobsClient
from job_market_intel.scrapers.hiiraan_jobs.config import HiiraanJobsSettings
from job_market_intel.scrapers.hiiraan_jobs.exceptions import (
    HiiraanJobsError,
    HiiraanJobsFetchError,
    HiiraanJobsParseError,
    HiiraanJobsResponseError,
)
from job_market_intel.scrapers.hiiraan_jobs.models import RawHiiraanJobsJob
from job_market_intel.scrapers.hiiraan_jobs.parser import HiiraanJobsParser, parse_detail
from job_market_intel.scrapers.hiiraan_jobs.pipeline import (
    HiiraanJobsPipeline,
    HiiraanJobsPipelineRunResult,
)

__all__ = [
    "HiiraanJobsCleaner",
    "HiiraanJobsClient",
    "HiiraanJobsError",
    "HiiraanJobsFetchError",
    "HiiraanJobsParseError",
    "HiiraanJobsParser",
    "HiiraanJobsPipeline",
    "HiiraanJobsPipelineRunResult",
    "HiiraanJobsResponseError",
    "HiiraanJobsSettings",
    "RawHiiraanJobsJob",
    "parse_detail",
]
