"""Fetches raw job data from 51job (前程无忧).

This module's only responsibility: make the HTTP requests (with retries
for transient failures), page through the search API, and hand back raw
dictionaries. It does not validate individual job fields — that is
``parser.py``'s job. Same fetch/validate/decide separation the other
scrapers establish.

Where the data lives (confirmed live, 2026-10-05)
--------------------------------------------------
51job (China) is a classic server-rendered board with a heavy WAF story
around its *pages* — and an undocumented JSON API around its *data*:

* **Search** — ``GET https://cupid.51job.com/pc/open/noauth/search-h5``
  with query params ``pageNum``, ``pageSize`` (≤100 confirmed), and an
  optional ``keyword`` (omitted → the board's general feed). Returns
  ``{"status": "1", "message": "成功", "resultbody": {"job": {"items":
  [...]}}}``; each item carries title, company, location, full
  description, posting timestamp, salary bounds, and employment type —
  **everything the pipeline needs in one request type, no per-job detail
  fetch** (the opposite of Job.am). No auth, no cookies, no signing.
  The API exposes a 1,000-item window (``totalCount`` caps at 1000;
  page 11 × 100 returns zero items), so a run pages through at most
  ``ceil(max_jobs_per_run / page_size)`` requests.

How this endpoint was found (the audit's "homepage references internal
JSON API" lead)
---------------------------------------------------------------
The PC homepage and its JS bundles expose the whole client stack: the
SPA search page (``we.51job.com/pc/search``), the ``cupid`` axios base
URL, and the ``/pc/open/noauth/*`` path family — including a request
interceptor that *computes* a ``sign`` header (MD5 over the canonical
query string plus a ``cupid_sign_key`` shipped in the page state,
``From-Domain``, ``uuid``). Probing showed **none of that is enforced
server-side**: the endpoint answers a bare GET with only a
browser-shaped User-Agent (the ``sign`` machinery exists for the SPA,
not as a gate — verified repeatedly during scoping). If enforcement ever
begins, the run fails loudly with ``Job51ResponseError`` (non-``"1"``
status or wrong shape) rather than silently; the sign key's location
above is the documented fallback path for that day.

What is deliberately *not* used here
------------------------------------
* **``msearch.51job.com``** (the public job pages linked from the
  homepage and referenced by ``jobHref``): behind an Aliyun WAF JS
  challenge that plain ``requests`` *and* ``curl_cffi`` browser
  impersonation both fail locally (96 KB challenge page, measured
  2026-10-05). Unneeded anyway — the list payload already carries every
  field the detail pages would provide.
* **``search.51job.com/list/*.html``**: returns an empty 200 body
  without the SPA's cookie/context (measured during scoping).
* **robots.txt**: does not exist (soft-404 page served with
  ``<meta name="robots" content="all">``), so no path restrictions
  apply. Politeness is still enforced here: ≤``max_jobs_per_run`` jobs
  per 12-hour run, a delay between page requests, and the documented
  UA.

Endpoint behavior this client depends on
----------------------------------------
* Page 1 ordering is *not* strictly by date (mix of fresh and older
  postings across the 1,000-item window) — we take the board's default
  order, like every other source takes its own.
* Duplicate ``jobId``s *do* occur within one window (2 of 300 during
  scoping) and duplicates within a batch would fail batch validation
  (``validation/common.py``), so entries are de-duplicated by
  ``jobId`` here, in first-seen order.
* A page that fails to grow the unique set (server ignoring
  ``pageNum`` someday) breaks the loop instead of spinning.
"""

from __future__ import annotations

import time
from urllib.parse import urlencode

from loguru import logger

from job_market_intel.common.http_client import (
    PermanentHTTPError,
    TransientHTTPError,
    fetch_json,
)
from job_market_intel.common.retry import call_with_retry

from .config import Job51Settings
from .exceptions import Job51FetchError, Job51ResponseError

#: The endpoint's own locale expectation; harmless but keeps the feed's
#: language stable regardless of where the runner executes.
_EXTRA_HEADERS = {"Accept-Language": "zh-CN,zh;q=0.9"}


class Job51Client:
    """Fetches the current 51job job records."""

    def __init__(self, settings: Job51Settings | None = None) -> None:
        self._settings = settings or Job51Settings()

    def _fetch_page(self, page: int) -> list[dict]:
        """Fetch one search page (with retries) and check its shape.

        Returns:
            The raw ``items`` list as served (not yet de-duplicated).

        Raises:
            Job51FetchError: The page could not be fetched after
                exhausting retries, or was permanently rejected.
            Job51ResponseError: The HTTP call succeeded but the payload
                wasn't the expected ``status == "1"`` job envelope —
                i.e. the undocumented API's contract changed.
        """
        params: dict[str, object] = {"pageNum": page, "pageSize": self._settings.page_size}
        keyword = (self._settings.keyword or "").strip()
        if keyword:
            params["keyword"] = keyword
        url = f"{self._settings.search_url}?{urlencode(params)}"

        def do_request():
            payload = fetch_json(
                url,
                timeout_seconds=self._settings.request_timeout_seconds,
                user_agent=self._settings.user_agent,
                extra_headers=_EXTRA_HEADERS,
            )
            if not isinstance(payload, dict) or payload.get("status") != "1":
                envelope = payload if isinstance(payload, dict) else type(payload).__name__
                raise Job51ResponseError(
                    f"51job page {page} returned an unexpected envelope "
                    f"(payload={envelope!r}). "
                    "The undocumented API's response shape may have changed."
                )
            resultbody = payload.get("resultbody")
            job_block = resultbody.get("job") if isinstance(resultbody, dict) else None
            items = job_block.get("items") if isinstance(job_block, dict) else None
            if not isinstance(items, list):
                raise Job51ResponseError(
                    f"51job page {page} had no resultbody.job.items list. "
                    "The undocumented API's response shape may have changed."
                )
            if not items and page == 1:
                # Observed once during scoping (2026-10-05): after several
                # rapid consecutive runs the API answered status="1" with an
                # empty first page, recovering seconds later — a soft
                # throttle, not a shape change. The general feed's first
                # page is never legitimately empty (1,000-item window), so
                # treat it as transient and let the shared retry/backoff
                # own the recovery instead of failing the whole run.
                raise TransientHTTPError(
                    "51job page 1 returned status=1 with zero items "
                    "(likely transient soft-throttling)"
                )
            return items

        try:
            return call_with_retry(
                do_request,
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
            )
        except TransientHTTPError as exc:
            raise Job51FetchError(
                f"Could not reach 51job (page {page}) after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise Job51FetchError(f"51job request failed permanently (page {page}): {exc}") from exc

    def fetch_raw_jobs(self) -> list[dict]:
        """Page through the search API until the run cap is reached.

        Returns:
            Raw job dictionaries in 51job's own field naming, first-seen
            order, de-duplicated by ``jobId``, capped at
            ``max_jobs_per_run`` items.

        Raises:
            Job51FetchError: A page failed after all retries.
            Job51ResponseError: The payload shape changed.
        """
        page_size = self._settings.page_size
        max_jobs = self._settings.max_jobs_per_run
        # The API's own window is 1,000 items (= 10 pages at 100/page);
        # ceil(max/page_size) + 1 requests is the most a capped run can
        # meaningfully make, and the no-growth break below catches an
        # ignored ``pageNum`` long before that.
        max_pages = (max_jobs + page_size - 1) // page_size + 1

        unique: dict[str, dict] = {}
        page = 1
        while page <= max_pages and len(unique) < max_jobs:
            items = self._fetch_page(page)
            if not items:
                break
            before = len(unique)
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                key = str(entry.get("jobId") or "").strip() or f"__anon_{page}_{len(unique)}"
                unique.setdefault(key, entry)
            if len(unique) == before:
                # Server ignored the page cursor (or the window is
                # exhausted with identical repeats) — stop instead of
                # re-fetching the same items forever.
                break
            if (
                self._settings.page_fetch_delay_seconds
                and len(unique) < max_jobs
                and page < max_pages
            ):
                time.sleep(self._settings.page_fetch_delay_seconds)
            page += 1

        capped = list(unique.values())[:max_jobs]
        if not capped:
            raise Job51ResponseError(
                "51job returned zero recognizable job records. The payload "
                "shape may have changed, or this may be an empty/blocked "
                "response."
            )
        logger.info(
            "51job list: {} unique jobs fetched across {} page(s), processing {} this run.",
            len(unique),
            page - 1,
            len(capped),
        )
        return capped
