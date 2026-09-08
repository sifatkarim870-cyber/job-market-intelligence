"""RemoteOK-specific exceptions.

Kept separate from ``src/common/http_client.py``'s generic
``TransientHTTPError``/``PermanentHTTPError`` on purpose: the common
exceptions describe *why* an HTTP call failed in general terms, while these
describe failures in terms a caller of the RemoteOK scraper actually cares
about ("RemoteOK could not be reached" vs. "RemoteOK responded but the
content wasn't a usable job list"). ``client.py`` catches the common,
generic exceptions and re-raises as these more specific ones.
"""

from __future__ import annotations


class RemoteOKError(Exception):
    """Base class for all RemoteOK scraper errors.

    Catch this to handle any RemoteOK failure generically.
    """


class RemoteOKFetchError(RemoteOKError):
    """Raised when the RemoteOK API could not be reached after exhausting all retry attempts.

    This means the whole scrape run failed — no jobs were retrieved at
    all. The caller (e.g. the scheduler in a later step) should log this as
    a failed run and alert, rather than silently continuing.
    """


class RemoteOKResponseError(RemoteOKError):
    """Raised when RemoteOK responded successfully, but the response body isn't a usable job list.

    For example: the response was valid JSON but not a list, or the list
    was empty in a way that suggests the feed's shape changed rather than
    "there happen to be zero jobs right now."
    """
