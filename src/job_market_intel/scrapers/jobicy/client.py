"""HTTP client for the Jobicy remote-jobs API.

No pagination exists here, so this client does not pretend otherwise: one run
issues at most ``max_requests_per_run`` calls, each a distinct tag/geo query,
and deduplicates by ``id`` because different queries overlap heavily.
"""

from __future__ import annotations

import itertools
import time

import requests
from loguru import logger

from job_market_intel.scrapers.jobicy.config import JobicySettings
from job_market_intel.scrapers.jobicy.exceptions import (
    JobicyError,
    JobicyPermanentError,
)


class JobicyClient:
    """Fetches job records from the Jobicy public API."""

    def __init__(self, settings: JobicySettings | None = None) -> None:
        self.settings = settings or JobicySettings()

    def fetch_raw_jobs(self) -> list[dict]:
        """One or more filtered queries, merged and deduplicated by ``id``."""
        collected: dict[str, dict] = {}
        for params in self._queries():
            for job in self._request(params):
                ident = job.get("id")
                if ident is None:
                    # No identity means no deduplication; skipping beats
                    # inventing an id that would collide with a real one.
                    continue
                collected[str(ident)] = job
        logger.info("Jobicy fetched {} unique postings", len(collected))
        return list(collected.values())

    def _queries(self) -> list[dict]:
        """The request parameter sets for this run.

        With no tags and no geos there is exactly one query: the whole feed.
        Once filters exist, the cross product of tags and geos is walked (and
        each half on its own), capped at ``max_requests_per_run`` so a long
        list of filters cannot silently turn into a long run.
        """
        base = {"count": self.settings.page_size}
        tags = [t for t in self.settings.tags if t]
        geos = [g for g in self.settings.geos if g]

        if not tags and not geos:
            return [base]

        queries: list[dict] = []
        if tags and geos:
            queries = [{**base, "tag": t, "geo": g} for t, g in itertools.product(tags, geos)]
        elif tags:
            queries = [{**base, "tag": t} for t in tags]
        else:
            queries = [{**base, "geo": g} for g in geos]
        return queries[: self.settings.max_requests_per_run]

    def _request(self, params: dict) -> list[dict]:
        url = f"{self.settings.base_url.rstrip('/')}{self.settings.jobs_path}"
        attempts = self.settings.max_retries + 1
        last: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=self.settings.request_timeout_seconds,
                    headers={
                        "User-Agent": self.settings.user_agent,
                        "Accept": "application/json",
                    },
                )
            except requests.RequestException as exc:
                # The base class, so ConnectionError/Timeout are covered here
                # rather than each needing its own clause.
                last = exc
                logger.warning(
                    "Jobicy transport error (attempt {}/{}): {}", attempt, attempts, str(exc)[:110]
                )
            else:
                if response.status_code == 200:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise JobicyPermanentError(
                            f"Jobicy returned non-JSON: {response.text[:120]!r}"
                        ) from exc
                    jobs = payload.get("jobs") if isinstance(payload, dict) else None
                    if jobs is None:
                        keys = list(payload)[:8] if isinstance(payload, dict) else type(payload)
                        raise JobicyPermanentError(
                            f"no 'jobs' key in Jobicy response for {params}; keys were {keys}"
                        )
                    return list(jobs)

                if response.status_code == 429 or response.status_code >= 500:
                    last = JobicyError(f"HTTP {response.status_code} from Jobicy")
                    logger.warning(
                        "Jobicy HTTP {} (attempt {}/{})",
                        response.status_code,
                        attempt,
                        attempts,
                    )
                else:
                    # Notably HTTP 400: this API rejects an unknown parameter
                    # with 400 rather than ignoring it, which is how `page`
                    # turned out to be unsupported.
                    raise JobicyPermanentError(
                        f"Jobicy returned HTTP {response.status_code} for {params}: "
                        f"{response.text[:140]!r}"
                    )

            if attempt < attempts:
                time.sleep(self.settings.retry_backoff_seconds * (2 ** (attempt - 1)))

        logger.error("Jobicy request failed after {} attempts: {}", attempts, last)
        return []
