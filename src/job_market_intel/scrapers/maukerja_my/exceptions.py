"""Exceptions for the MauKerja (maukerja.my) scraper."""

from __future__ import annotations


class MaukerjaMyError(Exception):
    """Base exception for all MauKerja scraper errors."""


class MaukerjaMyFetchError(MaukerjaMyError):
    """Raised when an HTTP request to a sitemap or an ad page fails."""


class MaukerjaMyParseError(MaukerjaMyError):
    """Raised when an ad page cannot be turned into a CleanedJob."""


class MaukerjaMyResponseError(MaukerjaMyError):
    """Raised when the site answers but the payload is not a usable page."""
