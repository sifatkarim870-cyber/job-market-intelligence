"""Custom exceptions for the JobNet (Myanmar) scraper."""


class JobnetError(Exception):
    """Base exception for all JobNet scraper errors."""


class JobnetFetchError(JobnetError):
    """Raised when an HTTP operation fails."""


class JobnetParseError(JobnetError):
    """Raised when parsing job content fails unexpectedly."""
