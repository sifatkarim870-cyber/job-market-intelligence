"""Errors specific to the Revolico (Cuba) scraper."""

from __future__ import annotations


class RevolicoCuError(Exception):
    """Base for every Revolico (Cuba) scraper error."""


class RevolicoCuFetchError(RevolicoCuError):
    """The HTTP request failed, or failed after every retry."""


class RevolicoCuResponseError(RevolicoCuError):
    """The request succeeded but the payload was not the shape we expect."""


class RevolicoCuParseError(RevolicoCuError):
    """An individual ad could not be turned into a validated model."""
