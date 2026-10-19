"""Fetches raw postings from Jobs.ge (Georgia).

One browser session for the whole run.

Measured 2026-10-18
--------------------
* **Two paths, two languages, and only one has the description.** The listing
  and the English titles come from ``/en/``; the ad body comes from ``/ge/``,
  which is the only path that carries it. The English detail page is a 548
  character stub ending in "See full text of this announcement in Georgian."
* **Pagination is ``?page=N``** on the listing only. The detail page takes the
  id and nothing else.
* Not Cloudflare-walled, so no browser-detection workaround is needed -- the
  browser is here because the listing is rendered, not because the site
  fights back.

robots.txt: ``User-agent: *`` / ``Allow: /``.
"""

from __future__ import annotations

import time

from loguru import logger
from playwright.sync_api import sync_playwright

from .config import JobsGeSettings
from .exceptions import JobsGeFetchError, JobsGeResponseError


class JobsGeClient:
    """Fetches postings from Jobs.ge using a headless browser."""

    def __init__(self, settings: JobsGeSettings | None = None) -> None:
        self._settings = settings or JobsGeSettings()

    def _open_browser(self):
        try:
            pw = sync_playwright().start()
        except Exception as exc:  # noqa: BLE001
            raise JobsGeFetchError(
                "could not start Playwright. `playwright install chromium` has to "
                f"have been run in this environment: {exc}"
            ) from exc
        try:
            browser = pw.chromium.launch(headless=self._settings.headless)
        except Exception as exc:  # noqa: BLE001
            pw.stop()
            raise JobsGeFetchError(
                "could not launch Chromium. On CI the workflow runs "
                "`playwright install --with-deps chromium` for any source flagged "
                "`browser: true` in config/sources.json; locally run "
                f"`uv run playwright install chromium`. Underlying error: {exc}"
            ) from exc
        return pw, browser

    def listing_url(self, page: int = 1) -> str:
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        return base if page <= 1 else f"{base}?page={page}"

    def detail_url(self, ad_id: str) -> str:
        """The Georgian path -- the only one with the ad's full text."""
        return f"{self._settings.base_url}/{self._settings.detail_lang}/?view=jobs&id={ad_id}"

    def _fetch(self, view, url: str) -> str:
        view.goto(
            url,
            wait_until="domcontentloaded",
            timeout=self._settings.page_load_timeout_seconds * 1000,
        )
        view.wait_for_timeout(int(self._settings.settle_wait_seconds * 1000))
        return view.content()

    def fetch_listing_page(self, page: int = 1) -> tuple[str, dict[str, dict]]:
        """Render one listing page. Returns ``(html, {ad_id: {...}})``.

        The HTML is returned as well as the parsed cards so a listing whose
        table shape changed is still diagnosable from the run log rather than
        only as "0 postings".
        """
        from .parser import parse_listing

        pw, browser = self._open_browser()
        try:
            view = browser.new_page(user_agent=self._settings.user_agent)
            html = self._fetch(view, self.listing_url(page))
        except Exception as exc:  # noqa: BLE001
            raise JobsGeFetchError(f"jobs.ge listing page {page} failed to render: {exc}") from exc
        finally:
            browser.close()
            pw.stop()

        cards = parse_listing(html, page)
        logger.info("jobs.ge listing page {}: {} ad(s)", page, len(cards))
        time.sleep(self._settings.inter_request_delay_seconds)
        return html, cards

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}

        for page in range(1, self._settings.max_pages + 1):
            try:
                _, cards = self.fetch_listing_page(page)
            except JobsGeFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("jobs.ge listing page {} failed: {}", page, exc)
                break
            if not cards:
                break
            new = 0
            for ad_id, meta in cards.items():
                if ad_id not in found:
                    found[ad_id] = meta
                    new += 1
            logger.info("jobs.ge page {}: {} new ({} total)", page, new, len(found))
            if len(found) >= self._settings.max_jobs_per_run:
                break

        if not found and not failures:
            raise JobsGeResponseError(
                "no postings found. An empty result here means the table markup "
                "changed -- not that the board is empty -- so it is raised "
                "rather than returned empty."
            )
        return found, failures

    def _render_many(self, ad_ids: list[str]) -> tuple[dict[str, str], dict[str, str]]:
        rendered: dict[str, str] = {}
        failures: dict[str, str] = {}
        pw, browser = self._open_browser()
        try:
            view = browser.new_page(user_agent=self._settings.user_agent)
            for ad_id in ad_ids:
                url = self.detail_url(ad_id)
                last: Exception | None = None
                for attempt in range(1, self._settings.detail_render_attempts + 1):
                    try:
                        rendered[ad_id] = self._fetch(view, url)
                        last = None
                        break
                    except Exception as exc:  # noqa: BLE001
                        last = exc
                        logger.warning(
                            "jobs.ge render attempt {}/{} failed for {}: {}",
                            attempt,
                            self._settings.detail_render_attempts,
                            ad_id,
                            str(exc)[:100],
                        )
                        if attempt < self._settings.detail_render_attempts:
                            time.sleep(self._settings.retry_backoff_seconds)
                            continue
                if last is not None:
                    failures[ad_id] = f"{type(last).__name__}: {str(last)[:120]}"
                time.sleep(self._settings.inter_request_delay_seconds)
        finally:
            browser.close()
            pw.stop()
        logger.info("jobs.ge rendered {} of {} detail page(s)", len(rendered), len(ad_ids))
        return rendered, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths()

        selected = list(discovered.items())[:budget]
        ad_ids = [ad_id for ad_id, _ in selected]

        rendered: dict[str, str] = {}
        if ad_ids:
            try:
                rendered, render_failures = self._render_many(ad_ids)
            except JobsGeFetchError as exc:
                failures["browser"] = str(exc)
                logger.error("jobs.ge browser unavailable: {}", exc)
            else:
                for ad_id in ad_ids:
                    if ad_id in render_failures:
                        failures[ad_id] = render_failures[ad_id]

        records: list[dict] = []
        for ad_id, meta in selected:
            html = rendered.get(ad_id)
            if html is None:
                failures.setdefault(ad_id, "detail page did not render")
            records.append(
                {
                    "job_id": ad_id,
                    "html": html,
                    "url": self.detail_url(ad_id),
                    "listing_page": meta.get("page"),
                    "hints": {
                        "title_en": meta.get("title_en"),
                        "company": meta.get("company"),
                        "published": meta.get("published"),
                        "deadline": meta.get("deadline"),
                    },
                }
            )

        if not records and not failures:
            raise JobsGeResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returned empty."
            )
        logger.info("jobs.ge: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures
