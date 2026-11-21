"""BongThom-specific exceptions.

Same role as the other sources' ``exceptions.py``: the shared
``common/http_client.py`` errors describe why an HTTP call failed in
general terms, while these describe failures in terms a caller of the
BongThom scraper cares about ("BongThom could not be reached" vs
"BongThom responded but the payload wasn't a usable job record").
``client.py`` catches the generic ones and re-raises these.
"""

from __future__ import annotations


class BongthomError(Exception):
    """Base class for all BongThom scraper errors."""


class BongthomFetchError(BongthomError):
    """A request failed after all retries.

    A failed discovery page ends the run (there is nothing to sweep when
    the feed itself is unreachable). A failed per-job request is logged and
    that job is degraded -- its structured content is dropped, or its
    workplace circumstances are dropped -- rather than aborting the batch:
    one flaky detail GET must not discard the rest of the run.
    """


class BongthomResponseError(BongthomError):
    """BongThom responded, but the payload wasn't a usable job feed.

    Raised for a discovery page that is not JSON, is missing its ``data``
    list, or has an empty first page -- a fully broken site (or a format
    change) fails loudly, never as a silent zero-jobs no-op.
    """
