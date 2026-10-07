"""Jobvision-specific exceptions.

Same role as ``scrapers/glints/exceptions.py``: the shared
``common/http_client.py`` errors describe why an HTTP call failed in
general terms, while these describe failures in terms a caller of the
Jobvision scraper cares about ("Jobvision could not be reached" vs
"Jobvision responded but the sitemap/API payload wasn't a usable job").
``client.py`` catches the generic ones and re-raises these.
"""

from __future__ import annotations


class JobvisionError(Exception):
    """Base class for all Jobvision scraper errors."""


class JobvisionFetchError(JobvisionError):
    """A Jobvision request failed after all retries.

    This means the whole scrape run failed — no jobs were retrieved.
    """


class JobvisionResponseError(JobvisionError):
    """Jobvision responded, but the payload wasn't a usable job list."""
