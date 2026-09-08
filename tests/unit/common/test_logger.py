"""Unit tests for job_market_intel.common.logger.configure_logging.

What these tests verify, and why each matters:
    - The log directory is created automatically if it doesn't exist yet
      — a first-time run on a fresh machine must not fail just because
      `logs/` isn't there.
    - An invalid log level fails fast with a clear ValueError at startup,
      per the "fail fast on bad config" principle, rather than silently
      being ignored or raising a confusing error deep inside Loguru.
    - A log file is actually created and actually receives log messages —
      not just that the function runs without error.

Each test uses pytest's `tmp_path` fixture for an isolated, throwaway
directory, so tests never write into your real project's `logs/` folder
or interfere with each other.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from loguru import logger

from job_market_intel.common.logger import configure_logging


class TestConfigureLoggingSetup:
    def test_creates_log_directory_if_missing(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "does_not_exist_yet"
        assert not log_dir.exists()

        configure_logging(log_dir=log_dir)

        assert log_dir.exists()
        assert log_dir.is_dir()

    def test_creates_log_file_with_default_name(self, tmp_path: Path) -> None:
        configure_logging(log_dir=tmp_path)
        assert (tmp_path / "job_market_intel.log").exists()

    def test_creates_log_file_with_custom_name(self, tmp_path: Path) -> None:
        configure_logging(log_dir=tmp_path, log_file_name="custom_name.log")
        assert (tmp_path / "custom_name.log").exists()


class TestConfigureLoggingValidation:
    def test_invalid_console_level_raises_value_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            configure_logging(log_dir=tmp_path, console_level="NOT_A_REAL_LEVEL")

    def test_invalid_file_level_raises_value_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            configure_logging(log_dir=tmp_path, file_level="ALSO_NOT_REAL")

    def test_valid_levels_are_case_insensitive(self, tmp_path: Path) -> None:
        # Should not raise, whether given as lowercase or uppercase.
        configure_logging(log_dir=tmp_path, console_level="debug", file_level="info")


class TestConfigureLoggingActuallyLogs:
    def test_log_message_is_written_to_file(self, tmp_path: Path) -> None:
        configure_logging(log_dir=tmp_path, console_level="INFO", file_level="DEBUG")
        logger.info("this is a distinctive test log message: {}", "xyz123")

        log_file = tmp_path / "job_market_intel.log"
        # Loguru's file sink is configured with enqueue=True (process-safe
        # writes), which means the write happens on a background thread.
        # complete() blocks until all queued messages have actually been
        # written, so this test isn't racing the logger.
        logger.complete()

        content = log_file.read_text(encoding="utf-8")
        assert "this is a distinctive test log message: xyz123" in content

    def test_debug_message_below_console_level_still_reaches_file(self, tmp_path: Path) -> None:
        """file_level defaults to DEBUG even when console_level is INFO,
        so nothing is lost from the file.
        """
        configure_logging(log_dir=tmp_path, console_level="INFO", file_level="DEBUG")
        logger.debug("a debug-level message that should still land in the file")
        logger.complete()

        content = (tmp_path / "job_market_intel.log").read_text(encoding="utf-8")
        assert "a debug-level message that should still land in the file" in content
