"""Jobinja-specific exceptions.

Same role as ``scrapers/glints/exceptions.py``: the shared
``common/http_client.py`` errors describe why an HTTP call failed in
general terms, while these describe failures in terms a caller of the
Jobinja scraper cares about ("Jobinja could not be reached" vs "Jobinja
responded but the listing/page payload wasn't a usable job list").
``client.py`` catches the generic ones and re-raises these.
"""

from __future__ import annotations


class JobinjaError(Exception):
    """Base class for all Jobinja scraper errors."""


class JobinjaFetchError(JobinjaError):
    """A Jobinja page could not be fetched after all retries.

    This means the whole scrape run failed — no jobs were retrieved.
    """


class JobinjaResponseError(JobinjaError):
    """Jobinja responded, but the payload wasn't a usable job list."""
