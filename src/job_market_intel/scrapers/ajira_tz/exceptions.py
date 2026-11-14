"""Ajira Tanzania scraper exceptions."""


class AjiraTzError(Exception):
    """Base exception for all Ajira TZ scraper errors."""


class AjiraTzFetchError(AjiraTzError):
    """Raised when an HTTP/network request to the Ajira GraphQL API fails."""


class AjiraTzParseError(AjiraTzError):
    """Raised when a GraphQL response cannot be parsed into a RawAjiraTzJob."""
