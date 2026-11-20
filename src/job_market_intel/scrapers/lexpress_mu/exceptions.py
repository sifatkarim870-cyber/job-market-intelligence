"""Errors specific to the L'Express Petites Annonces (Mauritius) scraper."""

from __future__ import annotations


class LexpressMuError(Exception):
    """Base for every L'Express Petites Annonces scraper error."""


class LexpressMuFetchError(LexpressMuError):
    """The HTTP request failed, or failed after every retry."""


class LexpressMuResponseError(LexpressMuError):
    """The request succeeded but the payload was not the shape we expect."""


class LexpressMuParseError(LexpressMuError):
    """An individual ad could not be turned into a validated model."""
