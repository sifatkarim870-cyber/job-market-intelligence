"""work.ua (Ukraine) scraper package."""

from __future__ import annotations

from .client import WorkUaClient
from .config import WorkUaSettings
from .exceptions import (
    WorkUaError,
    WorkUaFetchError,
    WorkUaParseError,
    WorkUaResponseError,
)
from .models import RawWorkUaJob, WorkUaPipelineRunResult
from .parser import WorkUaParser
from .pipeline import WorkUaPipeline

__all__ = [
    "RawWorkUaJob",
    "WorkUaClient",
    "WorkUaError",
    "WorkUaFetchError",
    "WorkUaParseError",
    "WorkUaParser",
    "WorkUaPipeline",
    "WorkUaPipelineRunResult",
    "WorkUaResponseError",
    "WorkUaSettings",
]
