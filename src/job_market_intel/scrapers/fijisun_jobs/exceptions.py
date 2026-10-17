"""Errors specific to the Fiji Sun jobs scraper."""

from __future__ import annotations


class FijiSunJobsError(Exception):
    """Base for every Fiji Sun jobs scraper error."""


class FijiSunJobsFetchError(FijiSunJobsError):
    """The HTTP request failed, or failed after every retry."""


class FijiSunJobsResponseError(FijiSunJobsError):
    """The request succeeded but the payload was not the shape we expect."""


class FijiSunJobsParseError(FijiSunJobsError):
    """An individual posting could not be turned into a validated model."""
