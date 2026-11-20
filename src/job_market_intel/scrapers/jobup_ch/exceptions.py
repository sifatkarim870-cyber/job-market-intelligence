"""Exceptions for the jobup.ch scraper."""

from __future__ import annotations


class JobupChError(Exception):
    """Base exception for all jobup.ch scraper errors."""


class JobupChFetchError(JobupChError):
    """Raised when an HTTP request to a sitemap or an ad page fails."""


class JobupChParseError(JobupChError):
    """Raised when an ad page cannot be turned into a CleanedJob."""


class JobupChResponseError(JobupChError):
    """Raised when the site answers but the payload is not a usable page."""
