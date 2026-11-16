"""Exceptions for the Gallito (Uruguay) scraper."""

from __future__ import annotations


class GallitoError(Exception):
    """Base exception for all Gallito scraper errors."""


class GallitoNetworkError(GallitoError):
    """Raised when an HTTP or network operation fails."""


class GallitoParseError(GallitoError):
    """Raised when parsing or extracting Gallito content fails."""
