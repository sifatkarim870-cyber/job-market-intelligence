"""Reed-specific exceptions.

Kept separate from ``common/http_client.py``'s generic
``TransientHTTPError``/``PermanentHTTPError`` on purpose, same reasoning
as ``scrapers/remoteok/exceptions.py``/``scrapers/remotive/exceptions.py``:
the common exceptions describe *why* an HTTP call failed in general terms,
while these describe failures in terms a caller of the Reed scraper
actually cares about. ``client.py`` catches the common, generic exceptions
and re-raises as these more specific ones.

One addition neither RemoteOK's nor Remotive's exception module needed:
``ReedAuthenticationError``. Neither of those sources requires an API key
at all, so "the key is missing or wrong" was never a distinct failure mode
worth its own exception. Reed requires HTTP Basic Auth (API key as
username, blank password) on every request — see ``client.py``'s module
docstring — so a bad or missing key is a real, distinct, common
first-run failure that deserves a clearer message than a generic 401
wrapped in ``ReedFetchError`` would give.
"""

from __future__ import annotations


class ReedError(Exception):
    """Base class for all Reed scraper errors.

    Catch this to handle any Reed failure generically.
    """


class ReedAuthenticationError(ReedError):
    """Raised when Reed rejects the configured API key (HTTP 401/403).

    Distinct from ``ReedFetchError`` because this is never transient and
    never fixed by retrying — the only fix is a valid ``REED_API_KEY``.
    """


class ReedFetchError(ReedError):
    """Raised when the Reed API could not be reached after exhausting all retry attempts.

    Covers both the Search and Details endpoints. Note that a single
    Details-fetch failure for one job, mid-batch, is handled by the
    pipeline (that one job is skipped and logged, same skip-don't-crash
    philosophy every other source's pipeline follows) rather than
    surfacing here — this exception means the failure was severe enough
    that the caller (``client.py``) gave up entirely on the specific call
    in question.
    """


class ReedResponseError(ReedError):
    """Raised when Reed responded successfully, but the response body isn't usable.

    For example: the response was valid JSON but not the expected
    ``{"results": [...], "totalResults": N}``-shaped dict for Search, or
    missing an expected field entirely for Details. Same
    "shape changed, not just empty" signal ``RemotiveResponseError``
    documents.
    """
