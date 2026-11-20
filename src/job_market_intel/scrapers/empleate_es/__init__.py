"""Empléate (Spain) scraper package."""

from __future__ import annotations

from .client import EmpleateEsClient
from .config import EmpleateEsSettings
from .exceptions import (
    EmpleateEsError,
    EmpleateEsFetchError,
    EmpleateEsParseError,
    EmpleateEsResponseError,
)
from .models import EmpleateEsPipelineRunResult, RawEmpleateEsJob
from .parser import EmpleateEsParser
from .pipeline import EmpleateEsPipeline
from .tls import build_ca_bundle

__all__ = [
    "EmpleateEsClient",
    "EmpleateEsError",
    "EmpleateEsFetchError",
    "EmpleateEsParseError",
    "EmpleateEsPipeline",
    "EmpleateEsPipelineRunResult",
    "EmpleateEsParser",
    "EmpleateEsResponseError",
    "EmpleateEsSettings",
    "RawEmpleateEsJob",
    "build_ca_bundle",
]
