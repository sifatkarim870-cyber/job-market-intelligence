"""Exceptions for the Jobindex (jobindex.dk) scraper."""

from __future__ import annotations


class JobIndexError(Exception):
    """Base exception for all Jobindex scraper errors."""


class JobIndexFetchError(JobIndexError):
    """Raised when an HTTP request to jobindex.dk fails or returns non-200."""


class JobIndexParseError(JobIndexError):
    """Raised when listing JSON or ad HTML cannot be parsed."""


class JobIndexResponseError(JobIndexError):
    """Raised when discovery succeeds but yields no postings (markup changed)."""
