"""Exception classes for the JobBKK (Thailand) scraper."""

from __future__ import annotations


class JobbkkError(Exception):
    """Base exception for all JobBKK scraper errors."""


class JobbkkAPIError(JobbkkError):
    """Raised when an HTTP request to JobBKK fails."""


class JobbkkParseError(JobbkkError):
    """Raised when parsing JobBKK JSON-LD or HTML fails."""
