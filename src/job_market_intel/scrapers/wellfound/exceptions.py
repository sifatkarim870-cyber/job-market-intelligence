"""Errors specific to the Wellfound scraper."""

from __future__ import annotations


class WellfoundError(Exception):
    """Base for every Wellfound scraper error."""


class WellfoundFetchError(WellfoundError):
    """The HTTP request failed, or failed after every retry."""


class WellfoundResponseError(WellfoundError):
    """The request succeeded but the payload was not the shape we expect.

    Raised rather than returned empty, because "the board ran out of postings"
    and "the page stopped rendering links" look identical to every downstream
    consumer, and only one of them is a bug.
    """


class WellfoundParseError(WellfoundError):
    """An individual posting could not be turned into a validated model."""
