"""Errors specific to the Alfred scraper."""

from __future__ import annotations


class AlfredError(Exception):
    """Base for every Alfred scraper error."""


class AlfredFetchError(AlfredError):
    """The HTTP request failed, or failed after every retry."""


class AlfredResponseError(AlfredError):
    """The request succeeded but the payload was not the shape we expect.

    Raised rather than returned empty, because "the board has no vacancies" and
    "the markup changed" look identical downstream.
    """


class AlfredParseError(AlfredError):
    """An individual posting could not be turned into a validated model."""
