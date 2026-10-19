"""Errors specific to the JobsIreland.ie scraper."""

from __future__ import annotations


class JobsIrelandError(Exception):
    """Base for every JobsIreland.ie scraper error."""


class JobsIrelandFetchError(JobsIrelandError):
    """The HTTP request failed, or failed after every retry."""


class JobsIrelandResponseError(JobsIrelandError):
    """The request succeeded but the payload was not the shape we expect."""


class JobsIrelandParseError(JobsIrelandError):
    """An individual posting could not be turned into a validated model."""
