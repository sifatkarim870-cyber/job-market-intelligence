"""Errors specific to the Vagas.com.br scraper."""

from __future__ import annotations


class VagasComBrError(Exception):
    """Base for every Vagas.com.br scraper error."""


class VagasComBrFetchError(VagasComBrError):
    """The HTTP request failed, or failed after every retry."""


class VagasComBrResponseError(VagasComBrError):
    """The request succeeded but the payload was not the shape we expect.

    Raised rather than returned empty, because "the board ran out of postings"
    and "the listing markup changed" look identical downstream.
    """


class VagasComBrParseError(VagasComBrError):
    """An individual posting could not be turned into a validated model."""
