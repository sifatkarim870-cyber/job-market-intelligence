"""Exception classes for the GoodWork (Canada) scraper."""

from __future__ import annotations


class GoodworkError(Exception):
    """Base exception for all GoodWork scraper errors."""


class GoodworkAPIError(GoodworkError):
    """Raised when an HTTP request to GoodWork fails."""


class GoodworkParseError(GoodworkError):
    """Raised when parsing GoodWork HTML content fails."""
