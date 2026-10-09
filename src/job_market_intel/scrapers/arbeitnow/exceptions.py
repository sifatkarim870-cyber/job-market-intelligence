"""Arbeitnow scraper exceptions.

Kept separate from the other sources' exception modules so an import error in
one scraper can never break another, and so callers can distinguish "the
network failed" from "the payload is not what we expected" -- the same boundary
``scrapers/remotive/exceptions.py`` draws.
"""

from __future__ import annotations


class ArbeitnowError(Exception):
    """Base for every Arbeitnow scraper failure."""


class ArbeitnowFetchError(ArbeitnowError):
    """The API could not be reached, or returned a permanent HTTP error."""


class ArbeitnowResponseError(ArbeitnowError):
    """The response was valid JSON but not shaped like a job feed."""


class ArbeitnowParseError(ArbeitnowError):
    """A record could not be parsed into a RawArbeitnowJob."""
