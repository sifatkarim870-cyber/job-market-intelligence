"""Emploi.cm (Cameroon) scraper package."""

from __future__ import annotations

from .client import EmploiCmClient, job_id_from_href
from .config import EmploiCmSettings
from .exceptions import (
    EmploiCmError,
    EmploiCmFetchError,
    EmploiCmParseError,
    EmploiCmResponseError,
)
from .models import EmploiCmPipelineRunResult, RawEmploiCmJob
from .parser import EmploiCmParser
from .pipeline import EmploiCmPipeline

__all__ = [
    "EmploiCmClient",
    "EmploiCmError",
    "EmploiCmFetchError",
    "EmploiCmParseError",
    "EmploiCmPipeline",
    "EmploiCmPipelineRunResult",
    "EmploiCmParser",
    "EmploiCmResponseError",
    "EmploiCmSettings",
    "RawEmploiCmJob",
    "job_id_from_href",
]
