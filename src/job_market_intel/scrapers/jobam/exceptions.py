"""Job.am-specific exceptions.

Same role as ``scrapers/emploitic/exceptions.py``: the shared
``common/http_client.py`` errors describe why an HTTP call failed in
general terms, while these describe failures in terms a caller of the
Job.am scraper cares about ("Job.am could not be reached" vs
"Job.am responded but the payload wasn't a usable job list").
``client.py`` catches the generic ones and re-raises these.
"""

from __future__ import annotations


class JobAmError(Exception):
    """Base class for all Job.am scraper errors."""


class JobAmFetchError(JobAmError):
    """The Job.am job list could not be fetched after all retries.

    This means the whole scrape run failed — no jobs were retrieved.
    (A failed *detail* page is deliberately not this: see
    ``client.py._get_detail_page`` — a dead or unreachable detail only
    costs one job's parseable fields, not the run.)
    """


class JobAmResponseError(JobAmError):
    """Job.am responded, but the payload wasn't a usable job list."""
