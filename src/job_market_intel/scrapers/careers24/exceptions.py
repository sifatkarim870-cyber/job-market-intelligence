"""Errors specific to the Careers24 scraper."""

from __future__ import annotations


class Careers24Error(Exception):
    """Base for every Careers24 scraper error."""


class Careers24FetchError(Careers24Error):
    """The HTTP request failed, or failed after every retry."""


class Careers24ResponseError(Careers24Error):
    """The request succeeded but the payload was not the shape we expect.

    Raised rather than returned empty, because "the board ran out of adverts"
    and "the listing markup changed" look identical downstream.
    """


class Careers24ParseError(Careers24Error):
    """An individual posting could not be turned into a validated model."""
