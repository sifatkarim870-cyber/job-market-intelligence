"""Errors specific to the Corporate Staffing Services (Kenya) scraper."""

from __future__ import annotations


class CorporateStaffingError(Exception):
    """Base for every Corporate Staffing scraper error."""


class CorporateStaffingFetchError(CorporateStaffingError):
    """The HTTP request failed, or failed after every retry."""


class CorporateStaffingResponseError(CorporateStaffingError):
    """The request succeeded but the payload was not the shape we expect."""


class CorporateStaffingParseError(CorporateStaffingError):
    """An individual posting could not be turned into a validated model."""
