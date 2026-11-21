"""Exceptions raised by the ANPE Mali scraper.

The hierarchy mirrors the other scrapers': one base class, a fetch error
for a discovery failure (nothing to show for the run), and a response
error for an envelope that arrived but cannot be trusted (shape change or
an unexpected block page).
"""

from __future__ import annotations


class AnpeMaliError(Exception):
    """Base class for every ANPE Mali scraper error."""


class AnpeMaliFetchError(AnpeMaliError):
    """A page could not be fetched after retries, or answered a fatal 4xx."""


class AnpeMaliResponseError(AnpeMaliError):
    """The endpoint answered, but not with the expected listing-array shape."""
