"""Ajira Portal (Tanzania) scraper package."""

from .config import AjiraTzSettings
from .exceptions import AjiraTzError, AjiraTzFetchError, AjiraTzParseError
from .pipeline import AjiraTzPipeline, AjiraTzPipelineRunResult

__all__ = [
    "AjiraTzError",
    "AjiraTzFetchError",
    "AjiraTzParseError",
    "AjiraTzPipeline",
    "AjiraTzPipelineRunResult",
    "AjiraTzSettings",
]
