"""Errors specific to the Forasna scraper."""

from __future__ import annotations


class ForasnaError(Exception):
    """Base for every Forasna scraper error."""


class ForasnaFetchError(ForasnaError):
    """The HTTP request failed, or failed after every retry."""


class ForasnaResponseError(ForasnaError):
    """The request succeeded but the payload was not the shape we expect."""


class ForasnaParseError(ForasnaError):
    """An individual posting could not be turned into a validated model."""
