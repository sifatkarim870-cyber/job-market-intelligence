"""Fetches raw postings from Hiiraan (Somalia).

Discovery is the listing page ``/jobs.php``, which links **16** postings as PDF
files (Terms of Reference). There is **no working pager**: ``/jobs.php?page=2``
returns 0 new links, so all postings are on one page.

Hrefs are **relative**. robots.txt disallows only ``/comments/`` and ``/social/``;
PDF postings are permitted.

Detail pages are **PDFs**, not HTML, so this client fetches bytes rather than
text. ``pypdf`` (a declared dependency) extracts the text.
"""

from __future__ import annotations

import re
import time

import requests
from loguru import logger

from .config import HiiraanJobsSettings
from .exceptions import HiiraanJobsFetchError, HiiraanJobsResponseError

_JOB_LINK = re.compile(r'href="(/uploads/[^"]+\.pdf)"')


class HiiraanJobsClient:
    """Fetches postings from Hiiraan (Somalia)."""

    def __init__(self, settings: HiiraanJobsSettings | None = None) -> None:
        self._settings = settings or HiiraanJobsSettings()

    def _fetch_pdf(self, url: str) -> bytes:
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": self._settings.user_agent, "Accept": "application/pdf"},
                timeout=self._settings.request_timeout_seconds,
            )
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as exc:
            raise HiiraanJobsFetchError(f"Hiiraan refused {url}: {exc}") from exc

    def listing_url(self, page: int = 1) -> str:
        base = f"{self._settings.base_url}{self._settings.listing_path}"
        return base if page <= 1 else f"{base}?page={page}"

    def fetch_listing_page(self, page: int = 1) -> dict[str, str]:
        import requests as _r

        resp = _r.get(
            self.listing_url(page),
            headers={"User-Agent": self._settings.user_agent, "Accept": "text/html"},
            timeout=self._settings.request_timeout_seconds,
        )
        resp.raise_for_status()
        html = resp.text
        found: dict[str, str] = {}
        for m in _JOB_LINK.finditer(html):
            path = m.group(1)
            slug = path.strip("/").split("/")[-1].replace(".pdf", "")
            # Skip procurement notices that are not job postings. Measured
            # 2026-10-18: 5 of 16 PDFs are real postings (TORs/advertisements)
            # and 11 are cancellation notices / REOI (Request for Expression of
            # Interest) notices. Fetching them wastes 11 requests and produces
            # 11 spurious "no Position Title" parse failures.
            low = slug.lower()
            if any(tok in low for tok in ("cancel", "reoi", "notice", "amendment")):
                continue
            found.setdefault(slug, path)
        logger.info("hiiraan listing page {}: {} link(s)", page, len(found))
        time.sleep(self._settings.inter_request_delay_seconds)
        return found

    def discover_detail_paths(self) -> tuple[dict[str, dict], dict[str, str]]:
        found: dict[str, dict] = {}
        failures: dict[str, str] = {}
        empty_streak = 0

        for page in range(1, self._settings.max_pages + 1):
            try:
                links = self.fetch_listing_page(page)
            except (HiiraanJobsFetchError, Exception) as exc:  # noqa: BLE001
                failures[f"page={page}"] = str(exc)
                logger.warning("hiiraan listing page {} failed: {}", page, exc)
                break
            if not links:
                empty_streak += 1
                if empty_streak >= self._settings.stop_after_repeated_empty_pages:
                    break
                continue
            new = 0
            for slug, path in links.items():
                if slug not in found:
                    found[slug] = {"path": path, "page": page}
                    new += 1
            short_page = len(links) < self._settings.min_links_per_page
            logger.info(
                "hiiraan page {}: {} new ({} total){}",
                page,
                new,
                len(found),
                " [short page, treating as the tail]" if short_page else "",
            )
            if len(found) >= self._settings.max_jobs_per_run or short_page:
                break
            empty_streak = 0

        if not found and not failures:
            raise HiiraanJobsResponseError(  # noqa: UP032
                f"no postings found in {self._settings.max_pages} page(s) of "
                f"{self._settings.listing_path}. An empty result here means the "
                "markup changed -- not that the board is empty -- so it is "
                "raised rather than returned empty."
            )
        return found, failures

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        budget = self._settings.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths()

        records: list[dict] = []
        for slug, meta in discovered.items():
            if len(records) >= budget:
                break
            url = "{}{}".format(self._settings.base_url, meta["path"])
            pdf_bytes = b""
            if self._settings.fetch_description:
                try:
                    pdf_bytes = self._fetch_pdf(url)
                except HiiraanJobsFetchError as exc:
                    failures[slug] = str(exc)
                    logger.warning("hiiraan job page {} failed: {}", slug, exc)
                time.sleep(self._settings.inter_request_delay_seconds)
            records.append(
                {
                    "job_id": slug,
                    "pdf_bytes": pdf_bytes,
                    "url": url,
                    "listing_page": meta["page"],
                }
            )

        if not records and not failures:
            raise HiiraanJobsResponseError(
                "discovery succeeded but every posting was dropped before "
                "fetching -- raised rather than returned empty."
            )
        logger.info("hiiraan: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures
