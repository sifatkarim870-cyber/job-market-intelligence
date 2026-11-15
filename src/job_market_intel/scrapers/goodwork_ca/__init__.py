"""GoodWork (Canada) scraper package."""

from __future__ import annotations

from .client import GoodworkClient
from .config import GoodworkSettings
from .exceptions import GoodworkAPIError, GoodworkError, GoodworkParseError
from .models import RawGoodworkJob
from .parser import GoodworkParser
from .pipeline import GoodworkPipeline, GoodworkPipelineRunResult

__all__ = [
    "GoodworkAPIError",
    "GoodworkClient",
    "GoodworkError",
    "GoodworkParseError",
    "GoodworkParser",
    "GoodworkPipeline",
    "GoodworkPipelineRunResult",
    "GoodworkSettings",
    "RawGoodworkJob",
]
