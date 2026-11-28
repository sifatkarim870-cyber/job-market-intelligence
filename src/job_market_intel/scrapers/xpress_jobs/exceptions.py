"""XpressJobs-specific exceptions.

Same role as ``scrapers/zangia_mn/exceptions.py``: the shared
``common/http_client.py`` errors describe why an HTTP call failed in
general terms, while these describe failures in terms a caller of the
XpressJobs scraper cares about ("XpressJobs could not be reached" vs
"XpressJobs responded but the payload wasn't a usable job list").
``client.py`` catches the generic ones and re-raises these.
"""

from __future__ import annotations


class XpressJobsError(Exception):
    """Base class for all XpressJobs scraper errors."""


class XpressJobsFetchError(XpressJobsError):
    """A listing or detail request failed after all retries.

    A failed listing page ends the run (there is nothing to sweep when the
    discovery cursor itself is unreachable). A failed detail request for a
    single job is logged and that job is skipped rather than aborting the
    batch -- one flaky detail GET must not discard the rest of the run.
    """


class XpressJobsResponseError(XpressJobsError):
    """XpressJobs answered, but the payload was not a usable job list.

    Raised when the listing endpoint returns something other than a JSON
    array, when the first page yields zero rows, or when no selected row
    carries a ``jobId``. This is the "reached it, but it is not what we
    expect" case -- distinct from a transport failure.
    """
