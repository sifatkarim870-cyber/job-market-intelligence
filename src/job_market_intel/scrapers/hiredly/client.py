"""Fetches raw postings from Hiredly (Malaysia).

The browser is started once per run and reused for the listing and every detail
page.

Three measured facts shape this module
--------------------------------------
1. **The host must be ``my.hiredly.com``.** ``hiredly.com/jobs/<slug>``
   redirects to the homepage, so a scraper that keeps the listing's apparent
   domain gets a page with no posting on it for every single row.
2. **The site rate-limits, and the symptom is deceptive.** After roughly 60-80
   detail requests in a few minutes, responses come back HTTP 200 with a
   perfectly good-looking title and **no ``#__NEXT_DATA__`` at all**. A run
   that reads the JSON blob with a fixed sleep therefore produces zero rows
   while reporting success. The client waits for ``#__NEXT_DATA__``
   explicitly, treats its absence as a fetch failure, and backs off before
   retrying.
3. **The listing paginates by ``?page=`` only.** 30 postings per page,
   verified distinct across pages 1, 2, 3, 5, 10 and 20.

``?signup=false`` is carried through: without it the listing redirects to a
variant URL and the page params behave inconsistently.

robots.txt: ``User-agent: *`` / ``Allow: /``.
"""

from __future__ import annotations

import time

from loguru import logger
from playwright.sync_api import sync_playwright

from .config import HiredlySettings
from .exceptions import HiredlyFetchError, HiredlyResponseError
from .parser import _slug_from_href

#: Runs in the page. One pass over the posting anchors; no per-card round trip.
_CARD_JS = """
() => {
  const out = [];
  for (const a of document.querySelectorAll('a[href^="/jobs/jobs-malaysia-"]')) {
    out.push({href: a.getAttribute('href')});
  }
  return out;
}
"""


class HiredlyClient:
    """Fetches postings from Hiredly using a headless browser."""

    def __init__(self, settings: HiredlySettings | None = None) -> None:
        self._settings = settings or HiredlySettings()

    def _open_browser(self):
        try:
            pw = sync_playwright().start()
        except Exception as exc:  # noqa: BLE001
            raise HiredlyFetchError(
                "could not start Playwright. `playwright install chromium` has to "
                f"have been run in this environment: {exc}"
            ) from exc
        try:
            browser = pw.chromium.launch(headless=self._settings.headless)
        except Exception as exc:  # noqa: BLE001
            pw.stop()
            raise HiredlyFetchError(
                "could not launch Chromium. On CI the workflow runs "
                "`playwright install --with-deps chromium` for any source flagged "
                "`browser: true` in config/sources.json; locally run "
                f"`uv run playwright install chromium`. Underlying error: {exc}"
            ) from exc
        return pw, browser

    def listing_url(self, page: int = 1) -> str:
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        return base if page <= 1 else f"{base}?page={page}&signup=false"

    def fetch_listing_page(self, page: int = 1) -> dict[str, dict]:
        """Render one listing page and return ``{slug: {path, page}}``."""
        pw, browser = self._open_browser()
        try:
            view = browser.new_page(user_agent=self._settings.user_agent)
            view.goto(
                self.listing_url(page),
                wait_until="domcontentloaded",
                timeout=self._settings.page_load_timeout_seconds * 1000,
            )
            view.wait_for_timeout(int(self._settings.render_wait_seconds * 1000))
            try:
                anchors = view.eval_on_selector_all(
                    'a[href^="/jobs/jobs-malaysia-"]',
                    "els => els.map(e => e.getAttribute('href'))",
                )
            except Exception as exc:  # noqa: BLE001
                raise HiredlyFetchError(
                    f"could not read the rendered listing on Hiredly: {exc}"
                ) from exc
        except HiredlyFetchError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HiredlyFetchError(f"Hiredly listing page {page} failed to render: {exc}") from exc
        finally:
            browser.close()
            pw.stop()

        found: dict[str, dict] = {}
        for href in anchors or []:
            slug = _slug_from_href(href)
            if slug is not None:
                found.setdefault(slug, {"path": f"/jobs/{slug}", "page": page})
        logger.info("hiredly listing page {}: {} card(s)", page, len(found))
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}

        for page in range(1, self._settings.max_pages + 1):
            try:
                cards = self.fetch_listing_page(page)
            except HiredlyFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("hiredly listing page {} failed: {}", page, exc)
                break
            if not cards:
                break
            new = 0
            for slug, meta in cards.items():
                if slug not in found:
                    found[slug] = meta
                    new += 1
            logger.info("hiredly page {}: {} new ({} total)", page, new, len(found))
            if len(found) >= self._settings.max_jobs_per_run:
                break

        if not found and not failures:
            raise HiredlyResponseError(
                "no postings found. An empty result here means the markup changed "
                "-- not that the board is empty -- so it is raised rather than "
                "returned empty."
            )
        return found, failures

    def _render_one(self, view, url: str) -> str:
        view.goto(
            url,
            wait_until="domcontentloaded",
            timeout=self._settings.page_load_timeout_seconds * 1000,
        )
        # The JSON blob is the whole record. Waiting for it -- rather than for a
        # clock -- is what distinguishes a rate-limited response from a slow
        # one: a rate-limited page never gets the element at all.
        view.wait_for_selector(
            "#__NEXT_DATA__",
            state="attached",
            timeout=self._settings.data_wait_seconds * 1000,
        )
        return view.content()

    def _render_many(self, urls: list[str]) -> tuple[dict[str, str], dict[str, str]]:
        """Render each URL in one browser session, backing off between retries.

        Returns ``(html_by_url, failures_by_url)``. Failures are reported rather
        than omitted, so the run's count is a real number and not a silent row
        discrepancy.
        """
        if not urls:
            return {}, {}
        rendered: dict[str, str] = {}
        failures: dict[str, str] = {}
        pw, browser = self._open_browser()
        try:
            view = browser.new_page(user_agent=self._settings.user_agent)
            for url in urls:
                last: Exception | None = None
                for attempt in range(1, self._settings.detail_render_attempts + 1):
                    try:
                        rendered[url] = self._render_one(view, url)
                        last = None
                        break
                    except Exception as exc:  # noqa: BLE001
                        last = exc
                        logger.warning(
                            "hiredly render attempt {}/{} failed for {}: {}",
                            attempt,
                            self._settings.detail_render_attempts,
                            url,
                            str(exc)[:100],
                        )
                        if attempt < self._settings.detail_render_attempts:
                            time.sleep(
                                self._settings.retry_backoff_seconds
                                + self._settings.inter_request_delay_seconds
                            )
                            continue
                if last is not None:
                    failures[url] = f"{type(last).__name__}: {str(last)[:120]}"
                time.sleep(self._settings.inter_request_delay_seconds)
        finally:
            browser.close()
            pw.stop()
        logger.info("hiredly rendered {} of {} detail page(s)", len(rendered), len(urls))
        return rendered, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths()

        selected = list(discovered.items())[:budget]
        urls = [f"{self._settings.base_url}{meta['path']}" for _, meta in selected]

        rendered: dict[str, str] = {}
        if urls:
            try:
                rendered, render_failures = self._render_many(urls)
            except HiredlyFetchError as exc:
                # The browser itself is unavailable. Every record then has no
                # HTML and the parser drops them all, so the run would report
                # "0 parsed" and exit 0. Record it instead.
                failures["browser"] = str(exc)
                logger.error("hiredly browser unavailable: {}", exc)
            else:
                for (slug, _), url in zip(selected, urls, strict=True):
                    if url in render_failures:
                        failures[slug] = render_failures[url]

        records: list[dict] = []
        for (slug, meta), url in zip(selected, urls, strict=True):
            html = rendered.get(url)
            if html is None:
                failures.setdefault(slug, "detail page did not render")
            records.append(
                {
                    "job_id": slug,
                    "html": html,
                    "url": url,
                    "listing_page": meta.get("page"),
                }
            )

        if not records and not failures:
            raise HiredlyResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returned empty."
            )
        logger.info("hiredly: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures
