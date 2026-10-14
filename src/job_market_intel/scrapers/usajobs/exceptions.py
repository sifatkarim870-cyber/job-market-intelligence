"""Errors specific to the USAJOBS scraper."""

from __future__ import annotations


class USAJobsError(Exception):
    """Base for every USAJOBS scraper error."""


class USAJobsAuthError(USAJobsError):
    """The API key was missing, malformed or rejected.

    Raised distinctly from a transport failure because the remedy is different:
    a 401 means "fix the credential", a timeout means "retry".
    """


class USAJobsFetchError(USAJobsError):
    """The HTTP request failed, or failed after every retry."""


class USAJobsResponseError(USAJobsError):
    """The request succeeded but the payload was not the shape we expect.

    Raised rather than returned empty, because "the board ran out of postings"
    and "the API changed its response envelope" look identical to every
    downstream consumer, and only one of them is a bug.
    """


class USAJobsParseError(USAJobsError):
    """An individual posting could not be turned into a validated model."""
