"""Jobindex (jobindex.dk) scraper package."""

from __future__ import annotations

from .client import (
    JobIndexClient,
    canonical_url,
    extract_stash,
    jobannonce_path,
    listing_results,
)
from .config import JobIndexSettings
from .exceptions import (
    JobIndexError,
    JobIndexFetchError,
    JobIndexParseError,
    JobIndexResponseError,
)
from .models import JobIndexPipelineRunResult, RawJobIndexJob
from .parser import JobIndexParser
from .pipeline import JobIndexPipeline

__all__ = [
    "JobIndexClient",
    "JobIndexError",
    "JobIndexFetchError",
    "JobIndexParseError",
    "JobIndexParser",
    "JobIndexPipeline",
    "JobIndexPipelineRunResult",
    "JobIndexResponseError",
    "JobIndexSettings",
    "RawJobIndexJob",
    "canonical_url",
    "extract_stash",
    "jobannonce_path",
    "listing_results",
]
