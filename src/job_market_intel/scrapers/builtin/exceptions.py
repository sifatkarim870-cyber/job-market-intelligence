"""Errors specific to the Built In scraper."""

from __future__ import annotations


class BuiltInError(Exception):
    """Base for every Built In scraper error."""


class BuiltInFetchError(BuiltInError):
    """The HTTP request failed, or failed after every retry."""


class BuiltInResponseError(BuiltInError):
    """The request succeeded but the payload was not the shape we expect.

    Raised rather than returned empty, because "the board ran out of postings"
    and "the JSON-LD shape changed" look identical downstream.
    """


class BuiltInParseError(BuiltInError):
    """An individual posting could not be turned into a validated model."""
