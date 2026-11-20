"""VDAB (Flanders, Belgium) scraper package."""

from __future__ import annotations

from .client import VdabClient
from .config import DEFAULT_MONITOR_KEY, VdabSettings
from .exceptions import (
    VdabError,
    VdabFetchError,
    VdabParseError,
    VdabResponseError,
)
from .models import RawVdabJob, VdabPipelineRunResult
from .parser import VdabParser
from .pipeline import VdabPipeline

__all__ = [
    "DEFAULT_MONITOR_KEY",
    "RawVdabJob",
    "VdabClient",
    "VdabError",
    "VdabFetchError",
    "VdabParseError",
    "VdabParser",
    "VdabPipeline",
    "VdabPipelineRunResult",
    "VdabResponseError",
    "VdabSettings",
]
