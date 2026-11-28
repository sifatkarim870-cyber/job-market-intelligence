"""Exceptions for the Vinnumalastofnun (Iceland) scraper."""

from __future__ import annotations


class VinnumalastofnunIsError(Exception):
    """Base exception for all Vinnumalastofnun scraper errors."""


class VinnumalastofnunIsFetchError(VinnumalastofnunIsError):
    """Raised when an HTTP request to island.is fails."""


class VinnumalastofnunIsParseError(VinnumalastofnunIsError):
    """Raised when a vacancy payload cannot be turned into a CleanedJob."""


class VinnumalastofnunIsResponseError(VinnumalastofnunIsError):
    """Raised when the API answers but the payload is not a usable document."""
