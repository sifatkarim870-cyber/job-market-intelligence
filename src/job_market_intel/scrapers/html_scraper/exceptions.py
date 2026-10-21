"""Errors specific to the HTML scraper framework."""

from __future__ import annotations


class HtmlScraperError(Exception):
    """Base for every HTML scraper framework error."""


class HtmlScraperFetchError(HtmlScraperError):
    """The HTTP request failed."""


class HtmlScraperResponseError(HtmlScraperError):
    """The request succeeded but the payload was not the expected shape."""


class HtmlScraperParseError(HtmlScraperError):
    """An individual posting could not be parsed."""
