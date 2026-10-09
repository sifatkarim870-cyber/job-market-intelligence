"""Fetches raw job feeds from Greenhouse's public board API.

One request per company board. Greenhouse has no combined feed, so this walks
a configured slug list rather than fetching one URL -- which is exactly why a
single generic scraper can cover an entire company's careers site and why
adding another 50 companies is a config edit rather than new code.

The per-board failure policy matters more here than for a single-board source.
One company changing ATS, or a typo in a slug, must not abort the run: a bad
board is recorded and skipped so the other boards still land. That is the
opposite of ``RemotiveClient``, where failing loudly is correct because there
is only one endpoint and a failure means something systemic is wrong.
"""

from __future__ import annotations

import time

from loguru import logger

from job_market_intel.common.http_client import (
    PermanentHTTPError,
    TransientHTTPError,
    fetch_json,
)
from job_market_intel.common.retry import call_with_retry

from .config import GreenhouseSettings
from .exceptions import GreenhouseFetchError, GreenhouseResponseError


class GreenhouseClient:
    """Fetches postings for a list of Greenhouse boards."""

    def __init__(self, settings: GreenhouseSettings | None = None) -> None:
        self._settings = settings or GreenhouseSettings()

    def board_url(self, slug: str) -> str:
        """Full API URL for one board, with the description HTML included.

        ``content=true`` is not optional for our purposes: without it every
        posting has an empty description, and description is the whole point.
        """
        return f"{self._settings.api_base_url}/{slug}/jobs?content=true"

    def fetch_board(self, slug: str) -> list[dict]:
        """Fetch one board's postings as raw dictionaries.

        Args:
            slug: The company's Greenhouse board slug, e.g. ``gitlab``.

        Returns:
            The postings from that board's ``jobs`` key.

        Raises:
            GreenhouseFetchError: The board could not be reached, or returned a
                permanent HTTP error (404 most often -- a slug that no longer
                exists). Not retried, because a retry cannot make a missing
                board appear.
            GreenhouseResponseError: Valid JSON, but not shaped like a board.
        """
        url = self.board_url(slug)
        try:
            payload = call_with_retry(
                fetch_json,
                url,
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
                timeout_seconds=self._settings.request_timeout_seconds,
                user_agent=self._settings.user_agent,
            )
        except PermanentHTTPError as exc:
            raise GreenhouseFetchError(f"Greenhouse board {slug!r} failed: {exc}") from exc
        except TransientHTTPError as exc:
            raise GreenhouseFetchError(
                f"Greenhouse board {slug!r} unreachable after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise GreenhouseResponseError(
                f"Board {slug!r} returned {type(payload).__name__}, expected a JSON object."
            )
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            raise GreenhouseResponseError(
                f"Board {slug!r} response has no 'jobs' list. The API shape may have changed."
            )
        return [entry for entry in jobs if isinstance(entry, dict)]

    def fetch_all(self) -> tuple[list[dict], dict[str, str]]:
        """Fetch every configured board, skipping the ones that fail.

        Returns:
            ``(records, failures)`` where ``records`` are raw job dicts from
            all healthy boards and ``failures`` maps slug -> reason. Callers
            log the failures instead of aborting: with a dozen boards, one
            company moving ATS should cost one board, not the run.
        """
        records: list[dict] = []
        failures: dict[str, str] = {}
        budget = self._settings.max_jobs_per_run

        for index, slug in enumerate(self._settings.company_slugs):
            if len(records) >= budget:
                logger.info(
                    "job budget of {} reached after {} board(s); skipping the rest",
                    budget,
                    index,
                )
                break
            try:
                jobs = self.fetch_board(slug)
            except (GreenhouseFetchError, GreenhouseResponseError) as exc:
                failures[slug] = str(exc)
                logger.warning("board {} failed: {}", slug, exc)
                continue
            except Exception as exc:  # noqa: BLE001 - never let one board kill the run
                failures[slug] = f"{type(exc).__name__}: {exc}"
                logger.warning("board {} raised unexpectedly: {}", slug, exc)
                continue

            logger.info("board {}: {} posting(s)", slug, len(jobs))
            records.extend(jobs)
            if index < len(self._settings.company_slugs) - 1:
                time.sleep(self._settings.inter_board_delay_seconds)

        if len(records) > budget:
            logger.warning(
                "fetched {} records, trimming to the {}-row budget", len(records), budget
            )
            records = records[:budget]
        return records, failures
