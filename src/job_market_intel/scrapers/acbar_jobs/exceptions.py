"""Errors specific to the ACBAR jobs scraper."""

from __future__ import annotations


class AcbarJobsError(Exception):
    """Base for every ACBAR jobs scraper error."""


class AcbarJobsFetchError(AcbarJobsError):
    """The HTTP request failed, or failed after every retry."""


class AcbarJobsResponseError(AcbarJobsError):
    """The request succeeded but the payload was not the shape we expect."""


class AcbarJobsParseError(AcbarJobsError):
    """An individual posting could not be turned into a validated model."""
