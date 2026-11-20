"""Emploi Bénin (Benin) scraper package."""

from __future__ import annotations

from .client import EmploiBeninClient, job_id_from_href
from .config import EmploiBeninSettings
from .exceptions import (
    EmploiBeninError,
    EmploiBeninFetchError,
    EmploiBeninParseError,
    EmploiBeninResponseError,
)
from .models import EmploiBeninPipelineRunResult, RawEmploiBeninJob
from .parser import EmploiBeninParser
from .pipeline import EmploiBeninPipeline

__all__ = [
    "EmploiBeninClient",
    "EmploiBeninError",
    "EmploiBeninFetchError",
    "EmploiBeninParseError",
    "EmploiBeninPipeline",
    "EmploiBeninPipelineRunResult",
    "EmploiBeninParser",
    "EmploiBeninResponseError",
    "EmploiBeninSettings",
    "RawEmploiBeninJob",
    "job_id_from_href",
]
