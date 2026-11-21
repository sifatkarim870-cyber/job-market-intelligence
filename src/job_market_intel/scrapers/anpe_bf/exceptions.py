"""Exceptions raised by the ANPE Burkina Faso scraper.

The hierarchy mirrors the other scrapers': one base class, a fetch error
for a discovery failure (nothing to show for the run), and a response
error for an envelope that arrived but cannot be trusted (shape change or
an unexpected block page).
"""

from __future__ import annotations


class AnpeBfError(Exception):
    """Base class for every ANPE Burkina Faso scraper error."""


class AnpeBfFetchError(AnpeBfError):
    """A page could not be fetched after retries, or answered a fatal 4xx."""


class AnpeBfResponseError(AnpeBfError):
    """The endpoint answered, but not with the expected post-array shape."""
