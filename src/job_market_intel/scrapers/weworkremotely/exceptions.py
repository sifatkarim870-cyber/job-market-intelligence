"""We Work Remotely-specific exceptions.

Kept separate from ``src/common/http_client.py``'s generic
``TransientHTTPError``/``PermanentHTTPError`` on purpose, mirroring
``scrapers/remoteok/exceptions.py`` exactly: the common exceptions describe
*why* an HTTP call failed in general terms, while these describe failures
in terms a caller of the We Work Remotely scraper actually cares about
("WWR could not be reached" vs. "WWR responded but the content wasn't a
usable job feed"). ``client.py`` catches the common, generic exceptions
and re-raises as these more specific ones.
"""

from __future__ import annotations


class WWRError(Exception):
    """Base class for all We Work Remotely scraper errors.

    Catch this to handle any WWR failure generically.
    """


class WWRFetchError(WWRError):
    """Raised when the We Work Remotely feed could not be reached after
    exhausting all retry attempts.

    This means the whole scrape run failed — no jobs were retrieved at
    all. The caller (e.g. the scheduler) should log this as a failed run
    and alert, rather than silently continuing.
    """


class WWRResponseError(WWRError):
    """Raised when We Work Remotely responded successfully, but the
    response body isn't a usable job feed.

    For example: the response was not valid XML at all, or it parsed but
    contained zero ``<item>`` entries in a way that suggests the feed's
    shape changed rather than "there happen to be zero jobs right now."
    """
