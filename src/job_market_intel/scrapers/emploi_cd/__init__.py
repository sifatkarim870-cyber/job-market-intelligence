"""Emploi.cd (DR Congo) scraper package."""

from __future__ import annotations

from .client import EmploiCdClient, job_id_from_href
from .config import EmploiCdSettings
from .exceptions import (
    EmploiCdError,
    EmploiCdFetchError,
    EmploiCdParseError,
    EmploiCdResponseError,
)
from .models import EmploiCdPipelineRunResult, RawEmploiCdJob
from .parser import EmploiCdParser
from .pipeline import EmploiCdPipeline

__all__ = [
    "EmploiCdClient",
    "EmploiCdError",
    "EmploiCdFetchError",
    "EmploiCdParseError",
    "EmploiCdPipeline",
    "EmploiCdPipelineRunResult",
    "EmploiCdParser",
    "EmploiCdResponseError",
    "EmploiCdSettings",
    "RawEmploiCdJob",
    "job_id_from_href",
]
