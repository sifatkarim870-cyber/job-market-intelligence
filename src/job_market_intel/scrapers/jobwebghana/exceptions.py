"""Errors specific to the Jobweb Ghana scraper."""

from __future__ import annotations


class JobwebGhanaError(Exception):
    """Base for every Jobweb Ghana scraper error."""


class JobwebGhanaFetchError(JobwebGhanaError):
    """The HTTP request failed, or failed after every retry."""


class JobwebGhanaResponseError(JobwebGhanaError):
    """The request succeeded but the payload was not the shape we expect."""


class JobwebGhanaParseError(JobwebGhanaError):
    """An individual posting could not be turned into a validated model."""
