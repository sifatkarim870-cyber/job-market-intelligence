"""Glints scraper.

Fetches job listings from Glints (https://glints.com), a Southeast-Asian
job platform (Indonesia/Singapore/Vietnam/Malaysia), validated into
typed ``RawGlintsJob`` objects.

Glints publishes no usable unauthenticated JSON API (``/api/v2/jobs``
returns 401 without a session), so the scraper discovers jobs via the
public sitemap index (``/sitemap_index.xml``, per-country job sitemaps
ordered newest-first) and fetches each job's server-rendered page, whose
full record is embedded in ``__NEXT_DATA__`` (~67 fields: title, Draft.js
description, salary, location, category, dates). ``/s/``-form sourced-job
URLs are rewritten to ``/jobs/`` to get the same full record (uuid-
guarded). Content arrives in the source language (Indonesian/Vietnamese/
English); non-English titles are translated by CI before classification,
descriptions by the local NLLB batch.

Typical usage:

    from job_market_intel.scrapers.glints import GlintsClient, GlintsParser, GlintsSettings

    settings = GlintsSettings()
    client = GlintsClient(settings=settings)
    parser = GlintsParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import GlintsClient
from .config import GlintsSettings
from .exceptions import GlintsError, GlintsFetchError, GlintsResponseError
from .models import RawGlintsJob
from .parser import GlintsParser
from .pipeline import GlintsPipeline, GlintsPipelineRunResult

__all__ = [
    "GlintsClient",
    "GlintsSettings",
    "GlintsError",
    "GlintsFetchError",
    "GlintsResponseError",
    "RawGlintsJob",
    "GlintsParser",
    "GlintsPipeline",
    "GlintsPipelineRunResult",
]
