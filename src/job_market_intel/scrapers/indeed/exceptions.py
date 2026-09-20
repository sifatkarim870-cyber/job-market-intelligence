"""Indeed-specific exceptions.

Mirrors the shape of scrapers/remoteok/exceptions.py etc. (a base error plus
narrow subclasses), with one addition specific to this scraper:
IndeedBlockedError. Nothing in the existing three scrapers needed a
"stop everything, don't retry" exception, because a bad HTTP response from
a JSON/RSS feed is just a transient fetch failure. A detected CAPTCHA/
challenge page or a run of consecutive failures on a real browser session
is a different kind of event — per this project's explicit instruction, the
scraper must recognize it and stop cleanly, not retry into a worse block and
not attempt to solve it.
"""

from __future__ import annotations


class IndeedError(Exception):
    """Base exception for all Indeed-scraper errors."""


class IndeedFetchError(IndeedError):
    """A page (search or detail) failed to load — timeout, driver error, or
    an unexpected non-2xx-equivalent outcome. Treated as transient by the
    pipeline: it counts toward ``max_consecutive_failures`` but does not by
    itself stop the session.
    """


class IndeedParseError(IndeedError):
    """A loaded page's HTML didn't match the expected structure for a
    single record (missing a required field, unrecognized card layout).
    Raised per-record, caught and logged by the parser exactly like the
    other three scrapers' skip-and-log-per-record behavior — one broken
    card must never abort a whole page.
    """


class IndeedBlockedError(IndeedError):
    """Raised when the session should stop immediately: a CAPTCHA/human-
    verification challenge was detected on the page, or
    ``max_consecutive_failures`` was reached. The pipeline catches this at
    the top level, closes the browser, marks the current
    ``ops.scrape_query_queue`` row ``failed`` with the reason recorded in
    ``last_error``, and ends the run. It must never be caught-and-retried
    anywhere below the pipeline's top level.
    """
