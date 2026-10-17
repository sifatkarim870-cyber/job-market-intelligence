"""Errors specific to the Jobs.af scraper."""

from __future__ import annotations


class JobsAfError(Exception):
    """Base for every Jobs.af scraper error."""


class JobsAfFetchError(JobsAfError):
    """The HTTP request failed, or failed after every retry."""


class JobsAfResponseError(JobsAfError):
    """The request succeeded but the payload was not the shape we expect."""


class JobsAfParseError(JobsAfError):
    """An individual posting could not be turned into a validated model."""
