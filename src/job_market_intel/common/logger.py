"""Centralized logging configuration.

Why this exists as a shared module: every scraper the platform ever adds
needs consistent, readable logs so a person can tell at a glance which
scraper produced a given line, and so log files don't pile up forever on
disk. Configuring Loguru once, here, guarantees every scraper logs the same
way instead of each one inventing its own format.

This module does not create a logger object for you to import. Instead you
call ``configure_logging()`` once, near the start of your program (for
example in a script's ``if __name__ == "__main__":`` block), and then every
module in the codebase can simply ``from loguru import logger`` and use it
immediately. That is the idiomatic way Loguru is designed to be used.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

VALID_LOG_LEVELS = frozenset({"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
"""Recognized Loguru severity levels.

Public (Step 15) so ``common.config.Settings`` can validate its
``log_level`` field against this exact set instead of maintaining a
second, independently-drifting copy of "what counts as a valid level."
"""


def configure_logging(
    log_dir: str | Path = "logs",
    *,
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    log_file_name: str = "job_market_intel.log",
    rotation: str = "10 MB",
    retention: str = "14 days",
) -> None:
    """Configure Loguru's global logger with a console sink and a rotating file sink.

    Args:
        log_dir: Directory where log files are written. Created automatically
            if it does not already exist.
        console_level: Minimum severity printed to the terminal. ``"INFO"`` is
            a sensible default so day-to-day runs aren't flooded with detail.
        file_level: Minimum severity written to the log file. Kept at
            ``"DEBUG"`` by default so the file has full detail even when the
            console is quieter, which matters when diagnosing a failed
            overnight scheduled run after the fact.
        log_file_name: Name of the log file inside ``log_dir``.
        rotation: When Loguru should start a new log file (size- or
            time-based). Prevents a single log file from growing forever.
        retention: How long old rotated log files are kept before Loguru
            deletes them automatically.

    Raises:
        ValueError: If ``console_level`` or ``file_level`` is not a
            recognized Loguru severity level. Failing fast here is
            deliberate: a typo'd log level should be caught immediately at
            startup, not silently ignored.
    """
    for level_name, level_value in (("console_level", console_level), ("file_level", file_level)):
        if level_value.upper() not in VALID_LOG_LEVELS:
            raise ValueError(
                f"{level_name}={level_value!r} is not a valid log level. "
                f"Choose one of: {sorted(VALID_LOG_LEVELS)}."
            )

    log_directory = Path(log_dir)
    log_directory.mkdir(parents=True, exist_ok=True)
    log_file_path = log_directory / log_file_name

    # Remove Loguru's default handler so we don't end up with duplicate,
    # differently-formatted log lines once we add our own sinks below.
    logger.remove()

    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    logger.add(sys.stderr, level=console_level.upper(), format=console_format, colorize=True)

    file_format = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
        "{name}:{function}:{line} - {message}"
    )
    logger.add(
        str(log_file_path),
        level=file_level.upper(),
        format=file_format,
        rotation=rotation,
        retention=retention,
        enqueue=True,  # process-safe writes; matters once APScheduler runs this concurrently later
        backtrace=True,
        diagnose=False,  # never log local variable values in production logs (may contain secrets)
    )

    logger.info(
        "Logging configured. Console level={}, file level={}, file={}",
        console_level.upper(),
        file_level.upper(),
        log_file_path,
    )
