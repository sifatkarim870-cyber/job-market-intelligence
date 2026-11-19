"""Exceptions for the Emploi.ci (Côte d'Ivoire) scraper."""

from __future__ import annotations


class EmploiCiError(Exception):
    """Base exception for all Emploi.ci scraper errors."""


class EmploiCiFetchError(EmploiCiError):
    """Raised when HTTP request to Emploi.ci fails or returns non-200."""


class EmploiCiParseError(EmploiCiError):
    """Raised when vacancy HTML or JSON-LD cannot be parsed."""
