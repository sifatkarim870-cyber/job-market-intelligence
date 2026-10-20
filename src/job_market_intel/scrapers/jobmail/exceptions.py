"""Errors specific to the JobMail scraper."""

from __future__ import annotations


class JobMailError(Exception):
    """Base for every JobMail scraper error."""


class JobMailFetchError(JobMailError):
    """The HTTP request failed, or failed after every retry."""


class JobMailResponseError(JobMailError):
    """The request succeeded but the payload was not the shape we expect."""


class JobMailParseError(JobMailError):
    """An individual posting could not be turned into a validated model."""
