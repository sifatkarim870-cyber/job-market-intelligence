"""Gallito (Uruguay) scraper package."""

from __future__ import annotations

from job_market_intel.scrapers.gallito_uy.client import GallitoClient
from job_market_intel.scrapers.gallito_uy.config import GallitoSettings
from job_market_intel.scrapers.gallito_uy.exceptions import (
    GallitoError,
    GallitoNetworkError,
    GallitoParseError,
)
from job_market_intel.scrapers.gallito_uy.models import (
    GallitoPipelineRunResult,
    RawGallitoJob,
)
from job_market_intel.scrapers.gallito_uy.parser import GallitoParser
from job_market_intel.scrapers.gallito_uy.pipeline import GallitoPipeline

__all__ = [
    "GallitoClient",
    "GallitoError",
    "GallitoNetworkError",
    "GallitoParseError",
    "GallitoParser",
    "GallitoPipeline",
    "GallitoPipelineRunResult",
    "GallitoSettings",
    "RawGallitoJob",
]
