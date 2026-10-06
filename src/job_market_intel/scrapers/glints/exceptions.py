"""Glints-specific exceptions.

Same role as ``scrapers/hrge/exceptions.py``: the shared
``common/http_client.py`` errors describe why an HTTP call failed in
general terms, while these describe failures in terms a caller of the
Glints scraper cares about ("Glints could not be reached" vs "Glints
responded but the sitemap/page payload wasn't a usable job list").
``client.py`` catches the generic ones and re-raises these.
"""

from __future__ import annotations


class GlintsError(Exception):
    """Base class for all Glints scraper errors."""


class GlintsFetchError(GlintsError):
    """A Glints page could not be fetched after all retries.

    This means the whole scrape run failed — no jobs were retrieved.
    """


class GlintsResponseError(GlintsError):
    """Glints responded, but the payload wasn't a usable job list."""
