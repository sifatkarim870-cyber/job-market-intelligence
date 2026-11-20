"""Exceptions for the VDAB (vdab.be) scraper."""

from __future__ import annotations


class VdabError(Exception):
    """Base exception for all VDAB scraper errors."""


class VdabFetchError(VdabError):
    """Raised when an HTTP request to vdab.be fails or returns non-200."""


class VdabParseError(VdabError):
    """Raised when a vacancy detail payload cannot be parsed."""


class VdabResponseError(VdabError):
    """Raised when discovery succeeds but the API returns no usable rows."""
