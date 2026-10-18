"""Errors specific to the JobSearch.az scraper."""

from __future__ import annotations


class JobSearchAzError(Exception):
    """Base for every JobSearch.az scraper error."""


class JobSearchAzFetchError(JobSearchAzError):
    """The browser request failed, or failed after every retry."""


class JobSearchAzResponseError(JobSearchAzError):
    """The request succeeded but the payload was not the shape we expect."""


class JobSearchAzParseError(JobSearchAzError):
    """An individual posting could not be turned into a validated model."""
