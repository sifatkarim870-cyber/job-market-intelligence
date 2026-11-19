"""Exceptions for the Emploi.cd (DR Congo) scraper."""

from __future__ import annotations


class EmploiCdError(Exception):
    """Base exception for all Emploi.cd scraper errors."""


class EmploiCdFetchError(EmploiCdError):
    """Raised when an HTTP request to Emploi.cd fails or returns non-200."""


class EmploiCdParseError(EmploiCdError):
    """Raised when vacancy HTML or JSON-LD cannot be parsed."""


class EmploiCdResponseError(EmploiCdError):
    """Raised when discovery succeeds but yields no postings (markup changed)."""
