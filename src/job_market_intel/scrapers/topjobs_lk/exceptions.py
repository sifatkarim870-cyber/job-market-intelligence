"""Errors specific to the TopJobs (Sri Lanka) scraper."""

from __future__ import annotations


class TopJobsLkError(Exception):
    """Base for every TopJobs scraper error."""


class TopJobsLkFetchError(TopJobsLkError):
    """The HTTP request failed, or failed after every retry."""


class TopJobsLkResponseError(TopJobsLkError):
    """The request succeeded but the payload was not the shape we expect."""


class TopJobsLkParseError(TopJobsLkError):
    """An individual posting could not be turned into a validated model."""
