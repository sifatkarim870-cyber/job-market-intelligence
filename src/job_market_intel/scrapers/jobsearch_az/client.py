"""Fetches raw postings from JobSearch.az (Azerbaijan).

Why a browser at all
--------------------
The site is a **Nuxt SPA**. Plain HTTP returns 512 KB of JavaScript bundle and
**zero** anchors -- the same symptom that made the workbook's "HTML scraper"
verdict wrong for keejob.com, hiredly.com and shine.com. Playwright renders the
page and exposes the postings.

Why the listing is read as DOM, not as a regex over HTML
-----------------------------------------------------------
Once rendered, the listing is a plain ``div.list__item`` card list and the
detail page has precise class hooks. Re-parsing ``page.content()`` with
BeautifulSoup -- the shape every other source in this project uses -- throws
both away: on the measured detail page the description text is 2,488 characters
while the whole-page text is 5,849 characters of navigation chrome. So the
client asks the DOM for exactly the fields it wants and hands the parser a
detail page's HTML only for the description body.

Measured on the live site 2026-10-18
------------------------------------
Listing card::

    div.list__item
      .list__item__text          "Sürücü\\nAmper Elektrik"   (title, then company)
      .list__item__end li        last li = date label
                                  "Bu gün" (today) | "Dünən" (yesterday) | "16 okt"
      .list__item__end li.money  ALWAYS RENDERED EMPTY -- the figure is injected
                                  after the snapshot, so no salary is available.

Detail page::

    h1.vacancy__title              "Resepşionist / Receptionist (Stomatoloji Klinika)"
    h1.company__title              "German Dental Clinic"
    .vacancy__deadline             "Son tarix 17 noy 2026"
    .vacancy__info .company__industry a       job category
    .company__body__text .company__industry a employer industry
    #content_block                 the description, and nothing else

The date label carries **no year** ("16 okt"), so the year is inferred: the
current year, rolled back one year if that would place the posting in the
future.

Hrefs are **relative**. robots.txt: ``User-agent: *`` / ``Allow: /``.
"""

from __future__ import annotations

import time

from loguru import logger
from playwright.sync_api import sync_playwright

from .config import JobSearchAzSettings
from .exceptions import JobSearchAzFetchError, JobSearchAzResponseError

#: Runs in the page. One pass over ``div.list__item``; no per-card round trip.
_CARD_JS = """
els => els.map(card => {
  const text = card.querySelector('.list__item__text');
  const end = card.querySelector('.list__item__end');
  const anchor = card.querySelector('a[href*="/vacancies/"]');
  const lis = end ? [...end.querySelectorAll('li')] : [];
  return {
    href: anchor ? anchor.getAttribute('href') : null,
    lines: text ? text.innerText.split('\\n').map(s => s.trim()).filter(Boolean) : [],
    dateLabel: lis.length ? (lis[lis.length - 1].textContent || '').trim() : null,
  };
})
"""

#: Non-posting anchors that share the ``/vacancies/`` prefix.
_NON_SLUGS = frozenset(
    {"undefined", "null", "page", "search", "browse", "category", "categories", "index"}
)


def _slug_from_href(href: str | None) -> str | None:
    """``/vacancies/amper-elektrik-surucu-150511`` -> ``amper-elektrik-surucu-150511``."""
    if not href or "/vacancies/" not in href:
        return None
    slug = href.split("/vacancies/", 1)[1].strip("/")
    slug = slug.split("?", 1)[0].split("#", 1)[0].strip("/")
    if not slug or slug.lower() in _NON_SLUGS or len(slug) < 5:
        return None
    if "/" in slug:  # a sub-tab such as /vacancies/<slug>/about-company
        return None
    return slug


class JobSearchAzClient:
    """Fetches postings from JobSearch.az using a headless browser.

    The browser is started once per run and reused for the listing and every
    detail page. Starting Chromium 30 times costs about 30 seconds of pure
    process launch and re-opens 30 fresh TCP connections to the site; one
    session is both faster and politer.
    """

    def __init__(self, settings: JobSearchAzSettings | None = None) -> None:
        self._settings = settings or JobSearchAzSettings()

    def _open_browser(self):
        """Start Playwright and Chromium, or explain what is missing."""
        try:
            pw = sync_playwright().start()
        except Exception as exc:  # noqa: BLE001
            raise JobSearchAzFetchError(
                "could not start Playwright. `playwright install chromium` has to "
                f"have been run in this environment: {exc}"
            ) from exc
        try:
            browser = pw.chromium.launch(headless=self._settings.headless)
        except Exception as exc:  # noqa: BLE001
            pw.stop()
            raise JobSearchAzFetchError(
                "could not launch Chromium. On CI the workflow runs "
                "`playwright install --with-deps chromium` for any source flagged "
                f"`browser: true` in config/sources.json; locally run "
                f"`uv run playwright install chromium`. Underlying error: {exc}"
            ) from exc
        return pw, browser

    def _render_one(self, view, url: str) -> str:
        """Render one detail page and return its HTML.

        Waiting on ``networkidle`` alone is not enough. The page paints the
        company block, the job title and the deadline from the first payload and
        then fills ``#content_block`` from a second request. Measured on
        2026-10-18, four of thirty postings came back with the header present
        and the description still empty -- ``networkidle`` had fired between
        the two, and those rows landed with ``description_clean = NULL``.

        So the description node is waited for explicitly, and its absence after
        a full timeout is an error rather than a short page. A posting with no
        description is not worth a row, and half of one is worse than none.
        """
        view.goto(
            url,
            wait_until="networkidle",
            timeout=self._settings.page_load_timeout_seconds * 1000,
        )
        view.wait_for_selector(
            "#content_block",
            state="attached",
            timeout=self._settings.description_wait_seconds * 1000,
        )
        return view.content()

    def _render_many(self, urls: list[str]) -> tuple[dict[str, str], dict[str, str]]:
        """Render each URL in one browser session.

        Returns ``(html_by_url, failures_by_url)``. A URL that never produced a
        description is reported rather than silently omitted, so the run's
        failure count is a real number instead of a row count discrepancy.
        """
        if not urls:
            return {}, {}
        rendered: dict[str, str] = {}
        failures: dict[str, str] = {}
        pw, browser = self._open_browser()
        try:
            view = browser.new_page(user_agent=self._settings.user_agent)
            for url in urls:
                for attempt in range(1, self._settings.detail_render_attempts + 1):
                    try:
                        rendered[url] = self._render_one(view, url)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "jobsearch_az render attempt {}/{} failed for {}: {}",
                            attempt,
                            self._settings.detail_render_attempts,
                            url,
                            exc,
                        )
                        if attempt < self._settings.detail_render_attempts:
                            time.sleep(self._settings.inter_request_delay_seconds)
                            continue
                        failures[url] = f"{type(exc).__name__}: {exc}"
                    else:
                        break
                time.sleep(self._settings.inter_request_delay_seconds)
        finally:
            browser.close()
            pw.stop()
        logger.info("jobsearch_az rendered {} of {} detail page(s)", len(rendered), len(urls))
        return rendered, failures

    @staticmethod
    def _click_load_more(page, attempts: int) -> None:
        """Click "Daha ətraflı" until the card count stops growing.

        The button sits under a sticky scroller, so Playwright's own click
        times out on the pointer-event check. ``force=True`` skips that check --
        the element is already confirmed visible and stable.
        """
        previous = -1
        for _ in range(attempts):
            count = len(page.query_selector_all("div.list__item"))
            if count == previous:
                break
            previous = count
            button = page.query_selector("a:has-text('Daha ətraflı')")
            if button is None:
                break
            try:
                button.click(timeout=4000, force=True)
            except Exception as exc:  # noqa: BLE001
                logger.debug("jobsearch_az 'load more' click failed: {}", exc)
                break
            page.wait_for_timeout(2500)

    def listing_url(self, page: int = 1) -> str:
        return f"{self._settings.base_url}{self._settings.listing_path}"

    def fetch_listing_page(self, page: int = 1) -> dict[str, dict]:
        """Render the listing and return ``{slug: {path, title, company, date_label, page}}``."""
        pw, browser = self._open_browser()
        try:
            view = browser.new_page(user_agent=self._settings.user_agent)
            view.goto(
                self.listing_url(page),
                wait_until="networkidle",
                timeout=self._settings.page_load_timeout_seconds * 1000,
            )
            view.wait_for_timeout(int(self._settings.render_wait_seconds * 1000))
            self._click_load_more(view, self._settings.max_load_more_clicks)
            try:
                cards = view.eval_on_selector_all("div.list__item", _CARD_JS)
            except Exception as exc:  # noqa: BLE001
                raise JobSearchAzFetchError(
                    f"could not read the rendered listing on jobsearch.az: {exc}"
                ) from exc
        except JobSearchAzFetchError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise JobSearchAzFetchError(
                f"jobsearch.az listing page {page} failed to render: {exc}"
            ) from exc
        finally:
            browser.close()
            pw.stop()

        found: dict[str, dict] = {}
        for card in cards or []:
            slug = _slug_from_href(card.get("href"))
            if slug is None:
                continue
            lines = [s for s in (card.get("lines") or []) if s]
            found.setdefault(
                slug,
                {
                    "path": f"/vacancies/{slug}",
                    "title": lines[0] if lines else None,
                    "company": lines[1] if len(lines) > 1 else None,
                    "date_label": card.get("dateLabel"),
                    "page": page,
                },
            )
        logger.info("jobsearch_az listing page {}: {} card(s)", page, len(found))
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}

        for page in range(1, self._settings.max_pages + 1):
            try:
                cards = self.fetch_listing_page(page)
            except JobSearchAzFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("jobsearch_az listing page {} failed: {}", page, exc)
                break
            if not cards:
                break
            new = 0
            for slug, meta in cards.items():
                if slug not in found:
                    found[slug] = meta
                    new += 1
            logger.info("jobsearch_az page {}: {} new ({} total)", page, new, len(found))
            if len(found) >= self._settings.max_jobs_per_run:
                break

        if not found and not failures:
            raise JobSearchAzResponseError(
                "no postings found. An empty result here means the markup changed "
                "-- not that the board is empty -- so it is raised rather than "
                "returned empty."
            )
        return found, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths()

        selected = list(discovered.items())[:budget]
        urls = [f"{self._settings.base_url}{meta['path']}" for _, meta in selected]

        rendered: dict[str, str] = {}
        failures: dict[str, str] = {}
        if self._settings.fetch_description and urls:
            try:
                rendered, render_failures = self._render_many(urls)
            except JobSearchAzFetchError as exc:
                # The browser itself is unavailable. Every record then has no
                # HTML and the parser drops them all, so the run would report
                # "0 parsed" and exit 0. Record it instead.
                failures["browser"] = str(exc)
                logger.error("jobsearch_az browser unavailable: {}", exc)
            else:
                for slug, url in zip((s for s, _ in selected), urls, strict=True):
                    if url in render_failures:
                        failures[slug] = render_failures[url]

        records: list[dict] = []
        for (slug, meta), url in zip(selected, urls, strict=True):
            html = rendered.get(url)
            if self._settings.fetch_description and html is None:
                failures.setdefault(slug, "detail page did not render")
            records.append(
                {
                    "job_id": slug,
                    "html": html,
                    "url": url,
                    "listing_page": meta.get("page"),
                    "hints": {
                        k: v for k, v in meta.items() if k in {"title", "company", "date_label"}
                    },
                }
            )

        if not records and not failures:
            raise JobSearchAzResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returned empty."
            )
        logger.info("jobsearch_az: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures
