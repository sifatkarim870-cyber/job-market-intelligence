"""Errors specific to the Hiredly scraper."""

from __future__ import annotations


class HiredlyError(Exception):
    """Base for every Hiredly scraper error."""


class HiredlyFetchError(HiredlyError):
    """The browser request failed, or failed after every retry."""


class HiredlyResponseError(HiredlyError):
    """The request succeeded but the payload was not the shape we expect."""


class HiredlyParseError(HiredlyError):
    """An individual posting could not be turned into a validated model."""
