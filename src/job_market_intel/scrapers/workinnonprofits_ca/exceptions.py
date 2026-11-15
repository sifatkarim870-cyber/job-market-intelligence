"""Custom exceptions for the WorkInNonProfits (Canada) scraper."""

from __future__ import annotations


class WorkInNonProfitsError(Exception):
    """Base exception for all WorkInNonProfits scraper errors."""


class WorkInNonProfitsAPIError(WorkInNonProfitsError):
    """Raised when an HTTP or network request fails."""


class WorkInNonProfitsParseError(WorkInNonProfitsError):
    """Raised when parsing or extracting job data fails."""
