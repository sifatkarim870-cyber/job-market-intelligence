"""Errors specific to the National Employment Agency (Cambodia) scraper."""

from __future__ import annotations


class NeaGovKhError(Exception):
    """Base for every NEA Cambodia scraper error."""


class NeaGovKhFetchError(NeaGovKhError):
    """The HTTP request failed, or failed after every retry."""


class NeaGovKhResponseError(NeaGovKhError):
    """The request succeeded but the payload was not the shape we expect."""


class NeaGovKhParseError(NeaGovKhError):
    """An individual vacancy could not be turned into a validated model."""
