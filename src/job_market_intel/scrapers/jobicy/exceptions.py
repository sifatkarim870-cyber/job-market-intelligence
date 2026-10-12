"""Errors raised by the Jobicy scraper."""


class JobicyError(Exception):
    """Base class for every Jobicy failure."""


class JobicyPermanentError(JobicyError):
    """A failure that will not resolve on retry (4xx, malformed payload)."""
