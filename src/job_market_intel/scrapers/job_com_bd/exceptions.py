"""Custom exceptions for the Job.com.bd scraper."""

from __future__ import annotations


class JobComBdError(Exception):
    """Base exception for all Job.com.bd scraper errors."""


class JobComBdAPIError(JobComBdError):
    """Raised when an HTTP or network request fails."""


class JobComBdParseError(JobComBdError):
    """Raised when parsing or extracting job data fails."""
