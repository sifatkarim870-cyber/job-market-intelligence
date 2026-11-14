"""Exceptions for the MojPosao (Croatia) scraper."""


class MojPosaoHrError(Exception):
    """Base exception for all MojPosao HR scraper errors."""


class MojPosaoHrFetchError(MojPosaoHrError):
    """Raised when an HTTP or network request fails."""


class MojPosaoHrParseError(MojPosaoHrError):
    """Raised when a job detail page cannot be parsed into a CleanedJob."""
