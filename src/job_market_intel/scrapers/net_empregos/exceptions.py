"""Errors specific to the Net-Empregos scraper."""

from __future__ import annotations


class NetEmpregosError(Exception):
    """Base for every Net-Empregos scraper error."""


class NetEmpregosFetchError(NetEmpregosError):
    """The HTTP request failed, or failed after every retry."""


class NetEmpregosResponseError(NetEmpregosError):
    """The request succeeded but the payload was not the shape we expect.

    Raised rather than returned empty, because "the board ran out of postings"
    and "the listing markup changed" look identical downstream.
    """


class NetEmpregosParseError(NetEmpregosError):
    """An individual posting could not be turned into a validated model."""
