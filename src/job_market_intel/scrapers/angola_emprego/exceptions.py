"""Errors specific to the Angola Emprego scraper."""

from __future__ import annotations


class AngolaEmpregoError(Exception):
    """Base for every Angola Emprego scraper error."""


class AngolaEmpregoFetchError(AngolaEmpregoError):
    """The HTTP request failed, or failed after every retry."""


class AngolaEmpregoResponseError(AngolaEmpregoError):
    """The request succeeded but the payload was not the shape we expect.

    Raised rather than returned empty, because "the board ran out of postings"
    and "the listing markup changed" look identical downstream.
    """


class AngolaEmpregoParseError(AngolaEmpregoError):
    """An individual posting could not be turned into a validated model."""
