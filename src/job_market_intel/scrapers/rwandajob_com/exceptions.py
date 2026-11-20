"""Exceptions for the Rwandajob.com (rwandajob.com) scraper."""

from __future__ import annotations


class RwandaJobError(Exception):
    """Base exception for all Rwandajob.com scraper errors."""


class RwandaJobFetchError(RwandaJobError):
    """Raised when an HTTP request to Rwandajob.com fails or returns non-200."""


class RwandaJobParseError(RwandaJobError):
    """Raised when vacancy HTML or JSON-LD cannot be parsed."""


class RwandaJobResponseError(RwandaJobError):
    """Raised when discovery succeeds but yields no postings (markup changed)."""
