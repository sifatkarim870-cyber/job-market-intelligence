"""Shared retry policy for transient network failures.

Why this is centralized: "how long to wait between retries" and "how many
times to try before giving up" are decisions, not plumbing. Every scraper in
this platform should retry transient failures (a dropped connection, a
timeout, a 500 from the remote server) the same sensible way, so this
behavior is tuned once, here, instead of being copy-pasted and drifting
between scrapers.

This module deliberately does NOT decide *what counts* as a transient
failure for a given source — that's supplied by the caller via
``retry_exception_types``, since "transient" can mean different exception
types depending on the HTTP library or wrapper a given scraper uses.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from loguru import logger
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

T = TypeVar("T")


def _log_before_retry(retry_state: RetryCallState) -> None:
    """Log a warning each time a retry is about to happen.

    Tenacity calls this automatically before it sleeps and retries. Logging
    here (rather than only logging the final failure) means a person
    watching the logs live can see "attempt 2 of 4 failed, retrying in
    2.1s" instead of just silence followed by either success or a final
    error.
    """
    attempt_number = retry_state.attempt_number
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "Retryable failure on attempt {}: {}. Retrying...",
        attempt_number,
        repr(exception),
    )


def build_retrying(
    *,
    retry_exception_types: type[BaseException] | tuple[type[BaseException], ...],
    max_attempts: int = 4,
    initial_wait_seconds: float = 1.0,
    max_wait_seconds: float = 30.0,
) -> Retrying:
    """Build a configured Tenacity ``Retrying`` object for transient HTTP failures.

    Args:
        retry_exception_types: The exception type (or tuple of types) that
            should trigger a retry. Any other exception is allowed to
            propagate immediately, since retrying a permanent failure (like
            "the URL doesn't exist") only wastes time.
        max_attempts: Total number of attempts, including the first one.
            Once exhausted, Tenacity re-raises the last exception.
        initial_wait_seconds: How long to wait before the first retry.
        max_wait_seconds: The retry wait time doubles after each attempt
            (exponential backoff) up to this ceiling, so a flaky endpoint
            doesn't result in an ever-growing wait.

    Returns:
        A ``Retrying`` instance. Call it as ``retrying(some_function, *args)``
        or use ``for attempt in retrying:`` per Tenacity's API.

    Why exponential backoff specifically: retrying immediately after a
    failure is likely to hit the same transient problem again (e.g. the
    remote server is briefly overloaded). Waiting progressively longer
    gives the problem time to resolve itself without hammering the server
    or making the caller wait an excessive fixed amount every time.
    """
    return Retrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=initial_wait_seconds, max=max_wait_seconds),
        retry=retry_if_exception_type(retry_exception_types),
        before_sleep=_log_before_retry,
        reraise=True,
    )


def call_with_retry(
    func: Callable[..., T],
    *args: object,
    retry_exception_types: type[BaseException] | tuple[type[BaseException], ...],
    max_attempts: int = 4,
    initial_wait_seconds: float = 1.0,
    max_wait_seconds: float = 30.0,
    **kwargs: object,
) -> T:
    """Convenience wrapper: call ``func(*args, **kwargs)`` under the retry policy above.

    This is the function most scrapers will actually call — it builds the
    ``Retrying`` object and immediately executes ``func`` under it, so
    callers don't need to import Tenacity directly.
    """
    retrying = build_retrying(
        retry_exception_types=retry_exception_types,
        max_attempts=max_attempts,
        initial_wait_seconds=initial_wait_seconds,
        max_wait_seconds=max_wait_seconds,
    )
    return retrying(func, *args, **kwargs)
