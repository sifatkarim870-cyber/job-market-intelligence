"""Greenhouse scraper exceptions.

Kept separate from the other sources' exception modules so an import error in
one scraper can never break another, and so callers can distinguish "the
network failed" from "the payload is not what we expected" -- the same
boundary ``scrapers/remotive/exceptions.py`` draws.
"""

from __future__ import annotations


class GreenhouseError(Exception):
    """Base for every Greenhouse scraper failure."""


class GreenhouseFetchError(GreenhouseError):
    """A board could not be reached, or returned a permanent HTTP error.

    A 404 here almost always means the slug does not exist or the company has
    moved off Greenhouse, so this is deliberately NOT retried: hammering a
    board that will never exist wastes the run's request budget.
    """


class GreenhouseResponseError(GreenhouseError):
    """The response was valid JSON but not shaped like a job board."""


class GreenhouseParseError(GreenhouseError):
    """A record could not be parsed into a RawGreenhouseJob."""
