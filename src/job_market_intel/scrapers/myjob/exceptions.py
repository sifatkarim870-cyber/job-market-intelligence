"""MyJob.mu-specific exceptions.

Same role as ``scrapers/emploitic/exceptions.py``: the shared
``common/http_client.py`` errors describe why an HTTP call failed in
general terms, while these describe failures in terms a caller of the
MyJob.mu scraper cares about ("MyJob.mu could not be reached" vs
"MyJob.mu responded but the payload wasn't a usable job list").
``client.py`` catches the generic ones and re-raises these.
"""

from __future__ import annotations


class MyJobError(Exception):
    """Base class for all MyJob.mu scraper errors."""


class MyJobFetchError(MyJobError):
    """The MyJob.mu API could not be fetched after all retries.

    This means the whole scrape run failed — no jobs were retrieved.
    """


class MyJobResponseError(MyJobError):
    """MyJob.mu responded, but the payload wasn't a usable job list."""
