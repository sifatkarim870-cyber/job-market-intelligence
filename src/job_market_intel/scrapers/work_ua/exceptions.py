"""Exceptions for the work.ua (Ukraine) scraper."""

from __future__ import annotations


class WorkUaError(Exception):
    """Base exception for all work.ua scraper errors."""


class WorkUaFetchError(WorkUaError):
    """Raised when an HTTP request to work.ua fails, or an ad page is gone."""


class WorkUaParseError(WorkUaError):
    """Raised when an ad page cannot be turned into a CleanedJob."""


class WorkUaResponseError(WorkUaError):
    """Raised when work.ua answers but the document is not a usable page."""
