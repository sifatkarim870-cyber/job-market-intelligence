"""Glints-specific exceptions.

Same role as ``scrapers/hrge/exceptions.py``: the shared
``common/http_client.py`` errors describe why an HTTP call failed in
general terms, while these describe failures in terms a caller of the
Glints scraper cares about ("Glints could not be reached" vs "Glints
responded but the sitemap/page payload wasn't a usable job list").
``client.py`` catches the generic ones and re-raises these.
"""

from __future__ import annotations


class GlintsError(Exception):
    """Base class for all Glints scraper errors."""


class GlintsFetchError(GlintsError):
    """A Glints page could not be fetched after all retries.

    This means the whole scrape run failed — no jobs were retrieved.
    """


class GlintsFirewallError(GlintsError):
    """Glints served its temporary firewall page (HTTP 403).

    This is a rate-limit response, not a permanent ban: the body is
    ``<title>Glints - Firewall</title>`` with
    ``<meta http-equiv="refresh" content="360">``, i.e. "come back in
    six minutes". ``client._request_text`` waits out the advertised
    cool-down (once per run) and retries; this error only escapes when
    the block outlasts that wait.
    """

    def __init__(self, message: str, cool_down_seconds: float) -> None:
        super().__init__(message)
        self.cool_down_seconds = cool_down_seconds


class GlintsResponseError(GlintsError):
    """Glints responded, but the payload wasn't a usable job list."""
