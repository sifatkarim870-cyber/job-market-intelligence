"""HTTP client for the Empléate (Spain) Solr search API.

The portal's AngularJS front end reads postings from
``open/offersearch/selectBuscador``. That endpoint is public
(``robots.txt`` allows ``/``) and returns the full posting inside the
listing document, so discovery and content retrieval are the same request.
That is why this source needs no per-ad detail call: one page of 100 costs
one HTTP request, against a corpus measured at 26,073 visible ads.

Three measured behaviours shape the code:

* ``rows`` is silently capped at 100 by the server, so ``page_size`` is
  validated to that value in ``config`` instead of asking for more.
* The default order is relevance. Runs pass
  ``sort=fechaCreacion desc,id desc``: the ``id`` tie-breaker is required
  because thousands of ads share a ``fechaCreacion`` second (nightly SNE
  batches), and without it page boundaries are not stable.
* ``start`` is a plain offset and works to the very end of the corpus
  (``start=26072`` returned the final document), which makes the rotating
  tail window a set of offset requests rather than a full walk.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import requests
from loguru import logger

from .config import EmpleateEsSettings
from .exceptions import EmpleateEsFetchError, EmpleateEsResponseError
from .models import RawEmpleateEsJob
from .tls import build_ca_bundle

#: Every field the parser reads. Asking for a fixed list keeps a page small
#: (the description dominates) and makes the contract with the parser explicit.
_FIELDS = ",".join(
    (
        "id",
        "titulo",
        "creador",
        "contenido",
        "ciudadF",
        "provinciaF",
        "paisF",
        "cp",
        "localizacion",
        "fechaCreacion",
        "fechaRevision",
        "salarioMin",
        "salarioMax",
        "verSalarioMin",
        "verSalarioMax",
        "tipoContrato",
        "tipoContratoN",
        "jornada",
        "jornadaF",
        "horario",
        "modality",
        "categoriaF",
        "subcategoriaF",
        "educacionReqF",
        "experienciaF",
        "speState",
        "url",
    )
)

#: The date sort plus an id tie-breaker. See the module docstring.
_SORT = "fechaCreacion desc,id desc"


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class EmpleateEsClient:
    """Client for the public Empléate (Spain) search API."""

    def __init__(self, settings: EmpleateEsSettings | None = None) -> None:
        self._settings = settings or EmpleateEsSettings()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._settings.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                "Referer": self._settings.base_url + "/empleo/",
            }
        )
        #: certifi's roots plus the intermediate this host omits. Never
        #: ``verify=False``: see tls.py for the measured chain.
        self._verify = self._settings.ca_bundle_path or build_ca_bundle()
        self._last_request_at: float | None = None

    def _throttle(self) -> None:
        """Polite gap between any two requests (robots.txt sets none)."""
        if self._last_request_at is None or self._settings.rate_limit_delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self._settings.rate_limit_delay - elapsed
        if wait > 0:
            time.sleep(wait)

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET and decode JSON with bounded backoff."""
        last_error: Exception | None = None
        wait = self._settings.retry_initial_wait_seconds

        for attempt in range(1, self._settings.max_retry_attempts + 1):
            self._throttle()
            payload: Any = None
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=self._settings.request_timeout,
                    verify=self._verify,
                )
                if response.status_code in (404, 410):
                    raise EmpleateEsFetchError(f"HTTP {response.status_code} for {url}")
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "Empléate request {}/{} failed for {} (start={}): {}",
                    attempt,
                    self._settings.max_retry_attempts,
                    url,
                    params.get("start"),
                    type(exc).__name__,
                )
                if attempt < self._settings.max_retry_attempts:
                    time.sleep(wait)
                    wait = min(wait * 2, self._settings.retry_max_wait_seconds)
                continue
            finally:
                self._last_request_at = time.monotonic()

            if not isinstance(payload, dict):
                raise EmpleateEsResponseError(
                    f"Empléate returned {type(payload).__name__}, not a JSON object, "
                    f"for {url} (start={params.get('start')})"
                )
            return payload

        raise EmpleateEsFetchError(
            f"Empléate refused {url} (start={params.get('start')}): {last_error}"
        ) from last_error

    def search_page(self, start: int) -> tuple[list[dict[str, Any]], int]:
        """Return ``(docs, num_found)`` for one offset page."""
        payload = self._get_json(
            self._settings.search_url,
            {
                "q.op": "AND",
                "q": "*",
                "wt": "json",
                "fq": "checkVisible:true",
                "fl": _FIELDS,
                "sort": _SORT,
                "rows": self._settings.page_size,
                "start": start,
            },
        )
        response = payload.get("response")
        if not isinstance(response, dict) or not isinstance(response.get("docs"), list):
            raise EmpleateEsResponseError(
                "Empléate search payload has no response.docs; the endpoint or its "
                f"response shape changed (keys={sorted(payload)[:8]})"
            )
        return response["docs"], _as_int(response.get("numFound"))

    def rotation_offset(self, pool_size: int, window: int) -> int:
        """Where the clock-driven archive window starts, relative to the pool.

        Advances one window-width per **hour**, so the four scheduled runs each
        read a different slice instead of all four re-reading the same one;
        over successive days the archive is tiled rather than sampled at one
        fixed point. ``start_offset`` is handled by ``fetch_jobs`` as an
        absolute corpus offset and never reaches this method.
        """
        if pool_size <= 0:
            return 0
        now = datetime.now()
        slot = now.toordinal() * 24 + now.hour
        return (slot * max(1, window)) % pool_size

    def _collect(
        self,
        docs: list[dict[str, Any]],
        page_start: int,
        collected: list[RawEmpleateEsJob],
        seen: set[str],
    ) -> int:
        """Append unseen documents, returning how many were new."""
        new = 0
        for document in docs:
            job_id = str(document.get("id") or "").strip()
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            collected.append(
                RawEmpleateEsJob(
                    job_id=job_id,
                    url=self._settings.site_offer_url_template.format(job_id=job_id),
                    search_page_start=page_start,
                    document=document,
                )
            )
            new += 1
        return new

    def _walk_fresh(
        self,
        collected: list[RawEmpleateEsJob],
        seen: set[str],
        total: int,
        fresh_n: int,
    ) -> tuple[int, int]:
        """Pull whole pages until the fresh region is covered.

        Returns ``(pages_scraped, next_start)``. ``next_start`` is the
        page-aligned floor of the archive window, so the two regions never
        overlap.
        """
        pages_scraped = 0
        next_start = self._settings.page_size
        while len(collected) < fresh_n and next_start < total:
            page_docs, _ = self.search_page(next_start)
            pages_scraped += 1
            if not page_docs:
                logger.warning(
                    "Empléate returned no docs at start={}; ending fresh walk.", next_start
                )
                break
            self._collect(page_docs, next_start, collected, seen)
            next_start += self._settings.page_size
        return pages_scraped, next_start

    def _walk_archive(
        self,
        collected: list[RawEmpleateEsJob],
        seen: set[str],
        total: int,
        budget: int,
        tail_floor: int,
    ) -> int:
        """Fill the remaining budget from a rotating archive window."""
        if len(collected) >= budget or tail_floor >= total:
            return 0

        page_size = self._settings.page_size
        pool = total - tail_floor
        pool_pages = max(1, (pool + page_size - 1) // page_size)
        remaining = budget - len(collected)
        pages_needed = (remaining + page_size - 1) // page_size

        if self._settings.start_offset is not None:
            # ``start_offset`` is an *absolute* corpus offset, not one relative
            # to the archive pool: pinning it must select the same pages
            # whether the fresh region covers 200 or 800 rows. Anything inside
            # the fresh region is pushed to its edge, then aligned down to a
            # page boundary.
            first = max(self._settings.start_offset, tail_floor)
            first -= first % page_size
            start_page = ((first - tail_floor) // page_size) % pool_pages
        else:
            start_page = (self.rotation_offset(pool, remaining) // page_size) % pool_pages

        pages_scraped = 0
        for offset_page in range(min(pages_needed, pool_pages)):
            if len(collected) >= budget:
                break
            index = (start_page + offset_page) % pool_pages
            page_start = tail_floor + index * page_size
            if page_start >= total:
                continue
            page_docs, _ = self.search_page(page_start)
            pages_scraped += 1
            if not page_docs:
                break
            self._collect(page_docs, page_start, collected, seen)
        return pages_scraped

    def fetch_jobs(self, max_jobs: int | None = None) -> tuple[list[RawEmpleateEsJob], int, int]:
        """Read the newest rows plus a rotating slice of the tail.

        Returns ``(raw_jobs, pages_scraped, total_available)``.
        """
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        if budget <= 0:
            return [], 0, 0

        collected: list[RawEmpleateEsJob] = []
        seen: set[str] = set()

        docs, total = self.search_page(0)
        pages_scraped = 1
        self._collect(docs, 0, collected, seen)

        if total <= 0:
            raise EmpleateEsResponseError(
                "Empléate reported numFound=0 for a visible-only query. The corpus "
                "was 26,073 ads on 2026-11-20, so an empty result means the query "
                "or the endpoint changed -- not that the board is empty."
            )

        budget = min(budget, total)
        fresh_n = min(self._settings.fresh_rows, budget)
        fresh_pages, next_start = self._walk_fresh(collected, seen, total, fresh_n)
        archive_pages = self._walk_archive(
            collected, seen, total, budget, tail_floor=min(next_start, total)
        )
        pages_scraped += fresh_pages + archive_pages

        selected = collected[:budget]
        logger.info(
            "Empléate: {} visible ad(s); selected {} across {} page request(s) "
            "(fresh={}, budget={}).",
            total,
            len(selected),
            pages_scraped,
            fresh_n,
            budget,
        )
        return selected, pages_scraped, total
