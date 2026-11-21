"""Zangia.mn-specific exceptions.

Same role as ``scrapers/timesjobs_in/exceptions.py``: the shared
``common/http_client.py`` errors describe why an HTTP call failed in
general terms, while these describe failures in terms a caller of the
Zangia scraper cares about ("Zangia could not be reached" vs "Zangia
responded but the payload wasn't a usable job list"). ``client.py``
catches the generic ones and re-raises these.
"""

from __future__ import annotations


class ZangiaError(Exception):
    """Base class for all Zangia scraper errors."""


class ZangiaFetchError(ZangiaError):
    """A listing or detail request failed after all retries.

    A failed listing page ends the run (there is nothing to sweep when the
    discovery cursor itself is unreachable). A failed detail request for a
    single job is logged and that job is skipped rather than aborting the
    batch -- one flaky detail GET must not discard the rest of the run.
    """


class ZangiaResponseError(ZangiaError):
    """Zangia responded, but the payload wasn't a usable job list.

    Raised for an empty first listing page (past ``start_page`` or a
    format/block change), an envelope without a usable ``data`` list
    (shape change), or a first page whose rows all failed to yield a
    ``code`` -- a fully broken site fails loudly, never as a silent
    zero-jobs no-op.
    """
