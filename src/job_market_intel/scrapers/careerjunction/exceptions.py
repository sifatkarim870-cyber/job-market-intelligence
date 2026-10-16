"""Errors specific to the CareerJunction scraper."""

from __future__ import annotations


class CareerJunctionError(Exception):
    """Base for every CareerJunction scraper error."""


class CareerJunctionFetchError(CareerJunctionError):
    """The HTTP request failed, or failed after every retry."""


class CareerJunctionResponseError(CareerJunctionError):
    """The request succeeded but the payload was not the shape we expect.

    Raised rather than returned empty, because "the board ran out of postings"
    and "the listing markup changed" look identical downstream.
    """


class CareerJunctionParseError(CareerJunctionError):
    """An individual posting could not be turned into a validated model."""
