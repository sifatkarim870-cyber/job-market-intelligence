"""Errors raised by the Kariyer.net scraper."""

from __future__ import annotations


class KariyerNetError(Exception):
    """Base class for every Kariyer.net scraper failure."""


class KariyerNetFetchError(KariyerNetError):
    """An HTTP request failed, or failed after every retry."""


class KariyerNetResponseError(KariyerNetError):
    """A request succeeded but the payload was not the shape we expect."""


class KariyerNetParseError(KariyerNetError):
    """An individual posting could not be turned into a validated model."""
