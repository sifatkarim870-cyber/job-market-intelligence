"""Errors raised by The Muse scraper."""


class ThemuseError(Exception):
    """Base class for every The Muse failure."""


class ThemusePermanentError(ThemuseError):
    """A failure that will not resolve on retry (4xx, malformed payload)."""
