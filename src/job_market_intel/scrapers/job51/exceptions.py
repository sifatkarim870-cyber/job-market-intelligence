"""51job-specific exceptions.

Same role as ``scrapers/jobam/exceptions.py``: the shared
``common/http_client.py`` errors describe why an HTTP call failed in
general terms, while these describe failures in terms a caller of the
51job scraper cares about ("51job could not be reached" vs "51job
responded but the payload wasn't a usable job list"). ``client.py``
catches the generic ones and re-raises these.
"""

from __future__ import annotations


class Job51Error(Exception):
    """Base class for all 51job scraper errors."""


class Job51FetchError(Job51Error):
    """A search page could not be fetched after all retries.

    This means the whole scrape run failed — no jobs were retrieved.
    (Individual malformed *records* are deliberately not this: see
    ``parser.py`` — one bad item skips, it never fails the run.)
    """


class Job51ResponseError(Job51Error):
    """51job responded, but the payload wasn't a usable job list.

    Raised when the HTTP call succeeded but the JSON shape is wrong
    (missing ``resultbody.job.items``, a non-``"1"`` status), i.e. the
    undocumented API's contract changed — visible immediately in CI
    rather than surfacing as a silent zero-job run.
    """
