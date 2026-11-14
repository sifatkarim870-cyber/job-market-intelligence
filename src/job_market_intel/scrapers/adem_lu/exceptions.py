"""Exceptions for the ADEM (Luxembourg) scraper."""

from __future__ import annotations


class AdemLuError(Exception):
    """Base exception for all ADEM scraper errors."""


class AdemLuFetchError(AdemLuError):
    """Raised when an HTTP request to ADEM's API fails or times out."""


class AdemLuParseError(AdemLuError):
    """Raised when an ADEM payload cannot be parsed."""
