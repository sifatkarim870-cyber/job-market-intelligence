"""Errors raised by the Himalayas scraper."""


class HimalayasError(Exception):
    """Base class for every Himalayas failure."""


class HimalayasPermanentError(HimalayasError):
    """A failure that will not resolve on retry (4xx, malformed payload)."""
