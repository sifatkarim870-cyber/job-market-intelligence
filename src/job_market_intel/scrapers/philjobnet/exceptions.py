"""Errors specific to the PhilJobNet scraper."""

from __future__ import annotations


class PhilJobNetError(Exception):
    """Base for every PhilJobNet scraper error."""


class PhilJobNetFetchError(PhilJobNetError):
    """The HTTP request failed, or failed after every retry."""


class PhilJobNetResponseError(PhilJobNetError):
    """The request succeeded but the payload was not the shape we expect."""


class PhilJobNetParseError(PhilJobNetError):
    """An individual posting could not be turned into a validated model."""
