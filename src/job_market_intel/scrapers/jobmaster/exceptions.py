"""JobMaster scraper errors.

One root so a run fails on a single ``except JobmasterError`` while
codes separate fetch (IO) from shape problems.
"""

from __future__ import annotations


class JobmasterError(Exception):
    """Base class for JobMaster scraper failures."""


class JobmasterFetchError(JobmasterError):
    """A page/API request failed after exhausting retries, or the host
    redirected into the login wall (pagination is anonymous-blocked)."""


class JobmasterResponseError(JobmasterError):
    """The site answered but with an unusable payload/shape."""
