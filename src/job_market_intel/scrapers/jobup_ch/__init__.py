"""jobup.ch scraper package -- Switzerland (French-speaking)."""

from __future__ import annotations

from .client import JobupChClient
from .config import JobupChSettings
from .exceptions import (
    JobupChError,
    JobupChFetchError,
    JobupChParseError,
    JobupChResponseError,
)
from .models import JobupChPipelineRunResult, RawJobupChJob, SitemapEntry
from .parser import JobupChParser
from .pipeline import JobupChPipeline

__all__ = [
    "JobupChClient",
    "JobupChError",
    "JobupChFetchError",
    "JobupChParseError",
    "JobupChPipeline",
    "JobupChPipelineRunResult",
    "JobupChParser",
    "JobupChResponseError",
    "JobupChSettings",
    "RawJobupChJob",
    "SitemapEntry",
]
