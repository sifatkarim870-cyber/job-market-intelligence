"""Errors specific to the JobsNepal scraper."""

from __future__ import annotations


class JobsNepalError(Exception):
    """Base for every JobsNepal scraper error."""


class JobsNepalFetchError(JobsNepalError):
    """The HTTP request failed, or failed after every retry."""


class JobsNepalResponseError(JobsNepalError):
    """The request succeeded but the payload was not the shape we expect."""


class JobsNepalParseError(JobsNepalError):
    """An individual posting could not be turned into a validated model."""
