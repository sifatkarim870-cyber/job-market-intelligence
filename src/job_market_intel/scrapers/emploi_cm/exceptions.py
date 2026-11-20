"""Exceptions for the Emploi.cm (emploi.cm) scraper."""

from __future__ import annotations


class EmploiCmError(Exception):
    """Base exception for all Emploi.cm scraper errors."""


class EmploiCmFetchError(EmploiCmError):
    """Raised when an HTTP request to Emploi.cm fails or returns non-200."""


class EmploiCmParseError(EmploiCmError):
    """Raised when vacancy HTML or JSON-LD cannot be parsed."""


class EmploiCmResponseError(EmploiCmError):
    """Raised when discovery succeeds but yields no postings (markup changed)."""
