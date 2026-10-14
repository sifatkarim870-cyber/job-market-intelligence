"""Errors specific to the Job Bank Canada scraper.

Split by cause so a network problem and a payload problem stay distinguishable
in the logs, matching every other source in this project.
"""

from __future__ import annotations


class JobBankError(Exception):
    """Base for every Job Bank scraper error."""


class JobBankFetchError(JobBankError):
    """The HTTP request failed, or failed after every retry."""


class JobBankResponseError(JobBankError):
    """The request succeeded but the response was not the shape we expect.

    Raised rather than returned when the page shape changes, because a scraper
    that silently parses an empty list looks exactly like a board that ran out
    of postings -- the same ambiguity this project has been bitten by before.
    """


class JobBankParseError(JobBankError):
    """An individual posting could not be turned into a validated model."""
