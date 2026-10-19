"""Errors specific to the Jobs.ge scraper."""

from __future__ import annotations


class JobsGeError(Exception):
    """Base for every Jobs.ge scraper error."""


class JobsGeFetchError(JobsGeError):
    """The browser request failed, or failed after every retry."""


class JobsGeResponseError(JobsGeError):
    """The request succeeded but the payload was not the shape we expect."""


class JobsGeParseError(JobsGeError):
    """An individual posting could not be turned into a validated model."""
