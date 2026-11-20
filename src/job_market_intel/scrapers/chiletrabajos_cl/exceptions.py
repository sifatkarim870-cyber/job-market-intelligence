"""Exceptions for the Chiletrabajos (chiletrabajos.cl) scraper."""

from __future__ import annotations


class ChiletrabajosClError(Exception):
    """Base exception for all Chiletrabajos scraper errors."""


class ChiletrabajosClFetchError(ChiletrabajosClError):
    """Raised when an HTTP request to the sitemap or an ad page fails."""


class ChiletrabajosClParseError(ChiletrabajosClError):
    """Raised when an ad page cannot be turned into a CleanedJob."""


class ChiletrabajosClResponseError(ChiletrabajosClError):
    """Raised when the site answers but the payload is not a usable page."""
