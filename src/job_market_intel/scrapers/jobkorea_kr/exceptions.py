"""Exceptions for the Jobkorea (South Korea) scraper."""

from __future__ import annotations


class JobkoreaError(Exception):
    """Base exception for all Jobkorea scraper errors."""


class JobkoreaNetworkError(JobkoreaError):
    """Raised when an HTTP or network operation fails."""


class JobkoreaParseError(JobkoreaError):
    """Raised when parsing or extracting Jobkorea content fails."""
