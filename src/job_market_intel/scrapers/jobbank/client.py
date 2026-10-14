"""Fetches raw postings from Job Bank Canada.

Job Bank has no public API, so this walks its HTML search and parses the result
cards, then optionally fetches each posting's detail page. Responsibilities are
kept to HTTP and shape-checking; field-level parsing is ``parser.py``'s job, so
a network failure and a data-quality failure stay distinguishable.

What was verified against the live site before this was written (2026-10-14):
``/jobsearch/jobsearch?term=<q>&page=<n>&sort=M`` returns 200 with results
anchored at ``a[href*='/jobsearch/jobposting/']``, 25 per page; detail pages at
``/jobsearch/jobposting/<id>`` return 200 and carry the body in
``.job-posting-details`` with salary and date in ``dd`` elements.
"""

from __future__ import annotations

import re
import time

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.common.http_client import (
    PermanentHTTPError,
    TransientHTTPError,
    fetch_html,
)
from job_market_intel.common.retry import call_with_retry

from .config import JobBankSettings
from .exceptions import JobBankFetchError, JobBankResponseError

#: /jobsearch/jobposting/50483505;jsessionid=ABC.jobsearch75?source=searchresults
#: Only the leading id is identity. The jsessionid rotates per session, so
#: including it would make every run look like a brand new posting.
_POSTING_ID_RE = re.compile(r"/jobsearch/jobposting/(\d+)")


class JobBankClient:
    """Fetches postings from Job Bank Canada's public job search."""

    def __init__(self, settings: JobBankSettings | None = None) -> None:
        self._settings = settings or JobBankSettings()

    # ------------------------------------------------------------------ URLs

    def search_url(self, term: str, page: int = 1) -> str:
        """URL for one page of results for one occupational term."""
        return (
            f"{self._settings.base_url}{self._settings.search_path}"
            f"?term={term.replace(' ', '+')}&page={page}&sort=M"
        )

    def posting_url(self, job_id: str) -> str:
        """URL for one posting's detail page."""
        return f"{self._settings.base_url}{self._settings.posting_path}/{job_id}"

    # --------------------------------------------------------------- fetching

    def _get(self, url: str) -> str:
        """Fetch one page, mapping transport failures onto our own errors."""
        try:
            return call_with_retry(
                fetch_html,
                url,
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
                timeout_seconds=float(self._settings.request_timeout_seconds),
                user_agent=self._settings.user_agent,
                extra_headers={"Accept-Language": self._settings.accept_language},
            )
        except TransientHTTPError as exc:
            raise JobBankFetchError(
                f"Job Bank unreachable after {self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise JobBankFetchError(f"Job Bank refused the request for {url}: {exc}") from exc

    def discover_postings(self, term: str) -> list[str]:
        """Posting ids visible for one occupational term, across its pages.

        Ids only -- the title is on the result card, but everything the corpus
        actually needs is on the detail page, so fetching that directly is
        cheaper than parsing the card and the page separately.
        """
        found: list[str] = []
        seen: set[str] = set()
        for page in range(1, self._settings.max_pages_per_term + 1):
            url = self.search_url(term, page)
            html = self._get(url)
            soup = BeautifulSoup(html, "html.parser")
            ids = [
                m.group(1)
                for m in (_POSTING_ID_RE.search(a.get("href", "")) for a in soup.select("a[href]"))
                if m
            ]
            if not ids:
                break  # walked past the last page
            new = [i for i in ids if i not in seen]
            seen.update(new)
            found.extend(new)
            logger.info("jobbank term={!r} page={}: {} new posting id(s)", term, page, len(new))
            if len(new) < self._settings.results_per_page:
                break
            time.sleep(self._settings.inter_page_delay_seconds)
        return found

    def fetch_posting(self, job_id: str) -> str:
        """Fetch one posting's detail page HTML."""
        return self._get(self.posting_url(job_id))

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Walk every search term and return raw posting dictionaries.

        Returns ``(records, failures)``. Callers log the failures rather than
        aborting: one posting that 500s must not cost a run's worth of good
        ones.

        ``max_jobs`` bounds the number of DETAIL pages fetched, because those
        are the expensive part -- one request each.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        seen: set[str] = set()
        records: list[dict] = []
        failures: dict[str, str] = {}

        for term in self._settings.default_search_terms:
            if len(records) >= budget:
                logger.info("jobbank: job budget of {} reached, stopping", budget)
                break
            try:
                ids = self.discover_postings(term)
            except (JobBankFetchError, JobBankResponseError) as exc:
                failures[f"term:{term}"] = str(exc)
                logger.warning("jobbank term {!r} failed: {}", term, exc)
                continue

            for job_id in ids:
                if job_id in seen:
                    continue
                if len(records) >= budget:
                    break
                seen.add(job_id)
                try:
                    html = self.fetch_posting(job_id)
                except JobBankFetchError as exc:
                    failures[job_id] = str(exc)
                    logger.warning("jobbank posting {} failed: {}", job_id, exc)
                    continue
                records.append({"job_id": job_id, "html": html, "search_term": term})
                time.sleep(self._settings.inter_page_delay_seconds)

        if not records and not failures:
            raise JobBankResponseError(
                "no postings discovered across "
                f"{len(self._settings.default_search_terms)} search terms. Either the "
                "term list has gone stale or the page shape changed -- this is "
                "raised rather than returned empty so the two cannot be confused."
            )
        return records, failures
