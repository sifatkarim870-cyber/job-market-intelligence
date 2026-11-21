"""Bdjobs-specific exceptions.

Same role as the other sources' ``exceptions.py``: the shared
``common/http_client.py`` errors describe why an HTTP call failed in
general terms, while these describe failures in terms a caller of the
Bdjobs scraper cares about ("Bdjobs could not be reached" vs "Bdjobs
responded but the payload wasn't a usable job record"). ``client.py``
catches the generic ones and re-raises these.
"""

from __future__ import annotations


class BdjobsError(Exception):
    """Base class for all Bdjobs scraper errors."""


class BdjobsFetchError(BdjobsError):
    """A search or detail request failed after all retries.

    A failed search page ends the run (there is nothing to sweep when the
    discovery feed itself is unreachable). A failed detail request for a
    single job is logged and that job is skipped rather than aborting the
    batch -- one flaky detail GET must not discard the rest of the run.
    """


class BdjobsResponseError(BdjobsError):
    """Bdjobs responded, but the payload wasn't a usable job feed.

    Raised for an empty first search page (a format/block change or a
    wrong endpoint) or an envelope whose ``data`` is not a list -- a fully
    broken site fails loudly, never as a silent zero-jobs no-op.
    """
