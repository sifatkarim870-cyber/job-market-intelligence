"""Exception classes for the Merojob (Nepal) scraper."""

from __future__ import annotations


class MerojobError(Exception):
    """Base exception for all Merojob scraper errors."""


class MerojobAPIError(MerojobError):
    """Raised when an API request to Merojob fails."""


class MerojobParseError(MerojobError):
    """Raised when parsing Merojob payload fails."""
