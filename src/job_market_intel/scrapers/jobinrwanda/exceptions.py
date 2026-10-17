"""Errors specific to the Job in Rwanda scraper."""

from __future__ import annotations


class JobInRwandaError(Exception):
    """Base for every Job in Rwanda scraper error."""


class JobInRwandaFetchError(JobInRwandaError):
    """The HTTP request failed, or failed after every retry."""


class JobInRwandaResponseError(JobInRwandaError):
    """The request succeeded but the payload was not the shape we expect."""


class JobInRwandaParseError(JobInRwandaError):
    """An individual posting could not be turned into a validated model."""
