"""Unit tests for job_market_intel.common.retry.

What these tests verify, and why each matters:
    - A function that succeeds immediately is called exactly once — retry
      logic must never add unnecessary overhead to the happy path.
    - A function that fails a few times and then succeeds is retried the
      right number of times and ultimately returns the successful result.
    - A function that always fails is retried up to (and not beyond)
      max_attempts, then the original exception is re-raised (not
      swallowed) so callers can handle it.
    - An exception type NOT in retry_exception_types is never retried —
      this is what lets callers distinguish "worth retrying" from "not
      worth retrying" failures.

All tests use near-zero wait times so the suite runs fast even though it's
exercising real Tenacity retry/backoff logic, not a mock of it.
"""

from __future__ import annotations

import pytest

from job_market_intel.common.retry import call_with_retry


class RetryableError(Exception):
    """Stand-in for a transient failure type, used only in these tests."""


class NonRetryableError(Exception):
    """Stand-in for a permanent failure type, used only in these tests."""


FAST_RETRY_KWARGS = {
    "retry_exception_types": RetryableError,
    "max_attempts": 4,
    "initial_wait_seconds": 0.01,
    "max_wait_seconds": 0.02,
}


class TestCallWithRetrySuccessPaths:
    def test_succeeds_immediately_calls_function_exactly_once(self) -> None:
        call_count = {"n": 0}

        def always_succeeds() -> str:
            call_count["n"] += 1
            return "ok"

        result = call_with_retry(always_succeeds, **FAST_RETRY_KWARGS)

        assert result == "ok"
        assert call_count["n"] == 1

    def test_succeeds_after_two_failures(self) -> None:
        call_count = {"n": 0}

        def fails_twice_then_succeeds() -> str:
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise RetryableError("simulated transient failure")
            return "recovered"

        result = call_with_retry(fails_twice_then_succeeds, **FAST_RETRY_KWARGS)

        assert result == "recovered"
        assert call_count["n"] == 3

    def test_passes_through_args_and_kwargs(self) -> None:
        def add(a: int, b: int, *, multiplier: int = 1) -> int:
            return (a + b) * multiplier

        result = call_with_retry(add, 2, 3, multiplier=10, **FAST_RETRY_KWARGS)
        assert result == 50


class TestCallWithRetryFailurePaths:
    def test_raises_original_exception_after_exhausting_attempts(self) -> None:
        call_count = {"n": 0}

        def always_fails() -> None:
            call_count["n"] += 1
            raise RetryableError("simulated permanent-feeling transient failure")

        with pytest.raises(RetryableError):
            call_with_retry(always_fails, **FAST_RETRY_KWARGS)

        assert call_count["n"] == FAST_RETRY_KWARGS["max_attempts"]

    def test_non_matching_exception_type_is_not_retried(self) -> None:
        call_count = {"n": 0}

        def fails_with_wrong_type() -> None:
            call_count["n"] += 1
            raise NonRetryableError("this type is not in retry_exception_types")

        with pytest.raises(NonRetryableError):
            call_with_retry(fails_with_wrong_type, **FAST_RETRY_KWARGS)

        assert call_count["n"] == 1, "A non-matching exception type must not trigger any retries"

    def test_tuple_of_retry_exception_types_both_trigger_retry(self) -> None:
        call_count = {"n": 0}

        def fails_with_either_type() -> str:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RetryableError("first failure")
            if call_count["n"] == 2:
                raise NonRetryableError("second failure, different type")
            return "ok"

        result = call_with_retry(
            fails_with_either_type,
            retry_exception_types=(RetryableError, NonRetryableError),
            max_attempts=4,
            initial_wait_seconds=0.01,
            max_wait_seconds=0.02,
        )
        assert result == "ok"
        assert call_count["n"] == 3
