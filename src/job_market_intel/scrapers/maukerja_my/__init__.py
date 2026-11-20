"""MauKerja (maukerja.my) scraper package -- Malaysia."""

from __future__ import annotations

from .client import MaukerjaMyClient
from .config import MaukerjaMySettings
from .exceptions import (
    MaukerjaMyError,
    MaukerjaMyFetchError,
    MaukerjaMyParseError,
    MaukerjaMyResponseError,
)
from .models import MaukerjaMyPipelineRunResult, RawMaukerjaMyJob, SitemapEntry
from .parser import MaukerjaMyParser
from .pipeline import MaukerjaMyPipeline

__all__ = [
    "MaukerjaMyClient",
    "MaukerjaMyError",
    "MaukerjaMyFetchError",
    "MaukerjaMyParseError",
    "MaukerjaMyPipeline",
    "MaukerjaMyPipelineRunResult",
    "MaukerjaMyParser",
    "MaukerjaMyResponseError",
    "MaukerjaMySettings",
    "RawMaukerjaMyJob",
    "SitemapEntry",
]
