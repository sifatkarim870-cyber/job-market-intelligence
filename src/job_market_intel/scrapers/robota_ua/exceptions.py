"""Exceptions for the Robota.ua (robota.ua, Ukraine) scraper."""

from __future__ import annotations


class RobotaUaError(Exception):
    """Base exception for all Robota.ua scraper errors."""


class RobotaUaFetchError(RobotaUaError):
    """Raised when an HTTP request to Robota.ua fails or returns a non-JSON body."""


class RobotaUaParseError(RobotaUaError):
    """Raised when a GraphQL vacancy payload cannot be parsed into a job."""


class RobotaUaResponseError(RobotaUaError):
    """Raised when discovery succeeds at the transport level but yields no postings.

    That means the ``publishedVacancies`` shape changed (or the search was
    blocked), not that the board is empty -- an empty board with known ids
    excluded is a successful no-op instead.
    """
