"""Exceptions for the Vrabotuvanje (North Macedonia) scraper."""


class VrabotuvanjeMkError(Exception):
    """Base exception for all Vrabotuvanje MK scraper errors."""


class VrabotuvanjeMkFetchError(VrabotuvanjeMkError):
    """Raised when an HTTP or network request fails."""


class VrabotuvanjeMkParseError(VrabotuvanjeMkError):
    """Raised when a job detail page cannot be parsed into a CleanedJob."""
