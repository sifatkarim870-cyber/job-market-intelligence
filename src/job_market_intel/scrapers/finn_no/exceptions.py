"""Exceptions for the FINN.no (Norway) scraper."""


class FinnNoError(Exception):
    """Base exception for all FINN.no scraper errors."""


class FinnNoFetchError(FinnNoError):
    """Raised when an HTTP or network request fails."""


class FinnNoParseError(FinnNoError):
    """Raised when a job detail page cannot be parsed into a CleanedJob."""
