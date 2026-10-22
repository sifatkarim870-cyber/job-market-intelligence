"""Exceptions for the generic browser scraper framework."""

from __future__ import annotations


class BrowserScraperError(Exception):
    """Base class for browser scraper failures."""


class BrowserFetchError(BrowserScraperError):
    """A page could not be loaded, or the browser session could not start."""


class BrowserChallengeError(BrowserScraperError):
    """The site served a bot challenge instead of its content.

    This is never solved. A challenge means the board refused this client;
    the run stops and says so, rather than storing an empty page.
    """
