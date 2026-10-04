"""Emploitic-specific exceptions.

Same role as ``scrapers/remotive/exceptions.py``: the shared
``common/http_client.py`` errors describe why an HTTP call failed in
general terms, while these describe failures in terms a caller of the
Emploitic scraper cares about ("Emploitic could not be reached" vs
"Emploitic responded but the payload wasn't a usable job list").
``client.py`` catches the generic ones and re-raises these.
"""

from __future__ import annotations


class EmploiticError(Exception):
    """Base class for all Emploitic scraper errors."""


class EmploiticFetchError(EmploiticError):
    """The Emploitic listing pages could not be fetched after all retries.

    This means the whole scrape run failed — no jobs were retrieved.
    """


class EmploiticResponseError(EmploiticError):
    """Emploitic responded, but the payload wasn't a usable job list."""
