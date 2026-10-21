"""Errors specific to the Shine.com scraper."""

from __future__ import annotations


class ShineError(Exception):
    """Base for every Shine.com scraper error."""


class ShineFetchError(ShineError):
    """The HTTP request failed, or failed after every retry."""


class ShineResponseError(ShineError):
    """The request succeeded but the payload was not the shape we expect."""


class ShineParseError(ShineError):
    """An individual posting could not be turned into a validated model."""
