"""Exceptions for the Empléate (Spain) scraper."""

from __future__ import annotations


class EmpleateEsError(Exception):
    """Base exception for all Empléate scraper errors."""


class EmpleateEsFetchError(EmpleateEsError):
    """Raised when an HTTP request to the Solr endpoint fails."""


class EmpleateEsParseError(EmpleateEsError):
    """Raised when a search document cannot be turned into a CleanedJob."""


class EmpleateEsResponseError(EmpleateEsError):
    """Raised when the API answers but the payload is not a usable Solr result."""
