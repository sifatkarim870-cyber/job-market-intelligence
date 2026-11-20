"""Exceptions for the Emploi Bénin (emploibenin.com) scraper."""

from __future__ import annotations


class EmploiBeninError(Exception):
    """Base exception for all Emploi Bénin scraper errors."""


class EmploiBeninFetchError(EmploiBeninError):
    """Raised when an HTTP request to Emploi Bénin fails or returns non-200."""


class EmploiBeninParseError(EmploiBeninError):
    """Raised when vacancy HTML or JSON-LD cannot be parsed."""


class EmploiBeninResponseError(EmploiBeninError):
    """Raised when discovery succeeds but yields no postings (markup changed)."""
