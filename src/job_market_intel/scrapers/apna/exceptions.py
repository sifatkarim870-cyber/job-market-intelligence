"""Errors specific to the Apna scraper."""

from __future__ import annotations


class ApnaError(Exception):
    """Base for every Apna scraper error."""


class ApnaFetchError(ApnaError):
    """The HTTP request failed, or failed after every retry."""


class ApnaResponseError(ApnaError):
    """The request succeeded but the payload was not the shape we expect.

    Raised rather than returned empty, because "the board ran out of postings"
    and "the listing markup changed" look identical downstream.
    """


class ApnaParseError(ApnaError):
    """An individual posting could not be turned into a validated model."""
