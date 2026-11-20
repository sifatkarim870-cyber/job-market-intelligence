"""Rwandajob.com (Rwanda) scraper package."""

from __future__ import annotations

from .client import RwandaJobClient, job_id_from_href
from .config import RwandaJobSettings
from .exceptions import (
    RwandaJobError,
    RwandaJobFetchError,
    RwandaJobParseError,
    RwandaJobResponseError,
)
from .models import RawRwandaJob, RwandaJobPipelineRunResult
from .parser import RwandaJobParser
from .pipeline import RwandaJobPipeline

__all__ = [
    "RawRwandaJob",
    "RwandaJobClient",
    "RwandaJobError",
    "RwandaJobFetchError",
    "RwandaJobParseError",
    "RwandaJobParser",
    "RwandaJobPipeline",
    "RwandaJobPipelineRunResult",
    "RwandaJobResponseError",
    "RwandaJobSettings",
    "job_id_from_href",
]
