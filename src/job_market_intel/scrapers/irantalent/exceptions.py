"""Irantalent-specific exceptions.

Same role as ``scrapers/jobvision/exceptions.py``: the shared
``common/http_client.py`` errors describe why an HTTP call failed in
general terms, while these describe failures in terms a caller of the
IranTalent scraper cares about ("IranTalent could not be reached" vs
"IranTalent responded but the search payload wasn't a usable job list").
``client.py`` catches the generic ones and re-raises these.
"""

from __future__ import annotations


class IrantalentError(Exception):
    """Base class for all Irantalent scraper errors."""


class IrantalentFetchError(IrantalentError):
    """A search request failed after all retries.

    Every page POST is discovery-critical (the search endpoint returns
    the records themselves — there is no second chance at a detail
    fetch), so both transient exhaustion and permanent HTTP failures
    mean the whole run failed: no jobs were retrieved.
    """


class IrantalentResponseError(IrantalentError):
    """IranTalent responded, but the payload wasn't a usable job list.

    Raised for an empty first search page (past ``start_page`` or a
    format/block change), a paginator envelope without a usable ``data``
    list (shape change), or a page whose rows all failed URL
    construction — a fully broken site fails loudly, never as a silent
    zero-jobs no-op.
    """
