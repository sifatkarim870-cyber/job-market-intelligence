"""Errors specific to the Nationale Vacaturebank (Netherlands) scraper."""

from __future__ import annotations


class NationaleVacaturebankNlError(Exception):
    """Base for every Nationale Vacaturebank scraper error."""


class NationaleVacaturebankNlFetchError(NationaleVacaturebankNlError):
    """The HTTP request failed, or failed after every retry."""


class NationaleVacaturebankNlResponseError(NationaleVacaturebankNlError):
    """The request succeeded but the payload was not the shape we expect."""


class NationaleVacaturebankNlParseError(NationaleVacaturebankNlError):
    """An individual ad could not be turned into a validated model."""
