"""Errors specific to the Karriere.at scraper."""

from __future__ import annotations


class KarriereAtError(Exception):
    """Base for every Karriere.at scraper error."""


class KarriereAtFetchError(KarriereAtError):
    """The HTTP request failed, or failed after every retry."""


class KarriereAtResponseError(KarriereAtError):
    """The request succeeded but the payload was not the shape we expect."""


class KarriereAtParseError(KarriereAtError):
    """An individual posting could not be turned into a validated model."""
