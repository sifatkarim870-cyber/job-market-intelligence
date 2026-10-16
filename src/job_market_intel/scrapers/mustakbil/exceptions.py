"""Errors specific to the Mustakbil scraper."""

from __future__ import annotations


class MustakbilError(Exception):
    """Base for every Mustakbil scraper error."""


class MustakbilFetchError(MustakbilError):
    """The HTTP request failed, or failed after every retry.

    Mustakbil answers a rate-limited burst with a connection-level failure
    rather than a 429, so this is the error that fires when the inter-request
    delay is set too low. It is a distinct type because the remedy is different:
    back off for minutes, do not just retry in seconds.
    """


class MustakbilResponseError(MustakbilError):
    """The request succeeded but the payload was not the shape we expect.

    Raised rather than returned empty, because "the board ran out of postings"
    and "the listing markup changed" look identical downstream.
    """


class MustakbilParseError(MustakbilError):
    """An individual posting could not be turned into a validated model."""
