"""Exceptions for the UWV Werk.nl (werk.nl) scraper."""

from __future__ import annotations


class WerkNlError(Exception):
    """Base exception for all Werk.nl scraper errors."""


class WerkNlFetchError(WerkNlError):
    """Raised when an HTTP request to the Werk.nl API fails."""


class WerkNlParseError(WerkNlError):
    """Raised when a vacancy payload cannot be turned into a CleanedJob."""


class WerkNlResponseError(WerkNlError):
    """Raised when the API answers but the payload is not a usable document."""
