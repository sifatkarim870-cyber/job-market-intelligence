"""Emploi.ci (Côte d'Ivoire) scraper package."""

from __future__ import annotations

from job_market_intel.scrapers.emploi_ci.client import EmploiCiClient
from job_market_intel.scrapers.emploi_ci.config import EmploiCiSettings
from job_market_intel.scrapers.emploi_ci.exceptions import (
    EmploiCiError,
    EmploiCiFetchError,
    EmploiCiParseError,
)
from job_market_intel.scrapers.emploi_ci.models import (
    EmploiCiPipelineRunResult,
    RawEmploiCiJob,
)
from job_market_intel.scrapers.emploi_ci.parser import EmploiCiParser
from job_market_intel.scrapers.emploi_ci.pipeline import EmploiCiPipeline

__all__ = [
    "EmploiCiClient",
    "EmploiCiError",
    "EmploiCiFetchError",
    "EmploiCiParseError",
    "EmploiCiPipeline",
    "EmploiCiPipelineRunResult",
    "EmploiCiParser",
    "EmploiCiSettings",
    "RawEmploiCiJob",
]
