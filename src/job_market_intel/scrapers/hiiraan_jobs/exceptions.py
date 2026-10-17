"""Errors specific to the Hiiraan jobs scraper."""

from __future__ import annotations


class HiiraanJobsError(Exception):
    """Base for every Hiiraan jobs scraper error."""


class HiiraanJobsFetchError(HiiraanJobsError):
    """The HTTP request failed, or failed after every retry."""


class HiiraanJobsResponseError(HiiraanJobsError):
    """The request succeeded but the payload was not the shape we expect."""


class HiiraanJobsParseError(HiiraanJobsError):
    """An individual posting could not be turned into a validated model."""
