"""OCC Mundial (Mexico) scraper exceptions.

The client is a slim subclass of the generic browser framework's client, so a
listing challenge and a failed fetch are still the framework's own error kinds.
These subclasses only give the package one coherent base for the runner and the
pipeline to name while remaining catchable as the framework errors they are.
"""

from __future__ import annotations

from job_market_intel.scrapers.browser_scraper.exceptions import (
    BrowserChallengeError,
    BrowserFetchError,
    BrowserScraperError,
)


class OccComMxError(BrowserScraperError):
    """Base class for all OCC Mundial scraper errors."""


class OccComMxFetchError(OccComMxError, BrowserFetchError):
    """A listing page or a detail payload could not be fetched."""


class OccComMxChallengeError(OccComMxError, BrowserChallengeError):
    """The site served a bot challenge instead of its content.

    Never solved: the run stops and says so, rather than storing the empty
    challenge document as if it were a posting.
    """
