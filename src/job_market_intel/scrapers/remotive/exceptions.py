"""Remotive-specific exceptions.

Kept separate from ``common/http_client.py``'s generic
``TransientHTTPError``/``PermanentHTTPError`` on purpose, same reasoning
as ``scrapers/remoteok/exceptions.py``: the common exceptions describe
*why* an HTTP call failed in general terms, while these describe failures
in terms a caller of the Remotive scraper actually cares about ("Remotive
could not be reached" vs. "Remotive responded but the content wasn't a
usable job list"). ``client.py`` catches the common, generic exceptions
and re-raises as these more specific ones.
"""

from __future__ import annotations


class RemotiveError(Exception):
    """Base class for all Remotive scraper errors.

    Catch this to handle any Remotive failure generically.
    """


class RemotiveFetchError(RemotiveError):
    """Raised when the Remotive API could not be reached after exhausting all retry attempts.

    This means the whole scrape run failed — no jobs were retrieved at
    all. The caller (e.g. the scheduler) should log this as a failed run
    and alert, rather than silently continuing.
    """


class RemotiveResponseError(RemotiveError):
    """Raised when Remotive responded successfully, but the response body isn't a usable job list.

    For example: the response was valid JSON but not the expected
    ``{"jobs": [...]}``-shaped dict, or the ``jobs`` list was present but
    empty in a way that suggests the feed's shape changed rather than
    "there happen to be zero jobs right now."
    """
