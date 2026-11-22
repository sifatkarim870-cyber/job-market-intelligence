"""Fetch OCC Mundial (occ.com.mx) postings.

Why this is not a JSON site config alone
----------------------------------------
The generic browser framework discovers postings from ``<a href>`` anchors on a
rendered listing page. OCC ships no such anchors: each result is
``<li class="vacancy-card" data-id="21428645">`` and the card navigates with a
JavaScript click, so anchor discovery finds nothing and the run would report an
empty board. The listing *does* publish every posting in a well-formed
schema.org ``ItemList`` JSON-LD block, and its ``itemListElement[].url`` values
are the canonical ad URLs. Discovery therefore reads that block.
The detail page is worse for the framework: its ``JobPosting`` JSON-LD is
PascalCase and ends in a stray ``;``, so ``json.loads`` rejects it. OCC instead
serves the same record as clean JSON from ``oferta.occ.com.mx`` -- no challenge,
no auth -- which is rendered through the shared ``mapped_json_html`` so the
parser, quality gate, validator, cleaner and persistence path stay the HTML
framework's own code.

Only the listing needs a browser. It is behind a Cloudflare managed challenge
that plain HTTP cannot clear; an undetected Chrome does, in about five seconds.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.browser_scraper.client import BrowserScraperClient
from job_market_intel.scrapers.browser_scraper.exceptions import (
    BrowserChallengeError,
    BrowserFetchError,
)
from job_market_intel.scrapers.html_scraper.client import mapped_json_html

from .exceptions import OccComMxChallengeError, OccComMxFetchError

#: URL path that identifies a posting card, used when the site config has no
#: ``id_url_regex`` of its own.
_DEFAULT_ID_REGEX = r"/oferta/(\d+)"


def _normalized_url(raw: str, base_url: str) -> str:
    """An absolute URL with its query, fragment and duplicate slashes removed.

    OCC's own ItemList emits ``https://www.occ.com.mx//empleo/oferta/...`` (a
    doubled slash). The path is identical to the one the site links, so it is
    collapsed here rather than left to produce two spellings of one ad.
    """
    parts = urlsplit(urljoin(base_url, raw))
    path = re.sub(r"/{2,}", "/", parts.path)
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _json_ld_nodes(payload: Any) -> list[dict[str, Any]]:
    """Every object in a JSON-LD document, walking ``@graph`` recursively."""
    if isinstance(payload, list):
        return [node for item in payload for node in _json_ld_nodes(item)]
    if not isinstance(payload, dict):
        return []
    nodes: list[dict[str, Any]] = [payload]
    graph = payload.get("@graph")
    if isinstance(graph, list):
        nodes.extend(node for item in graph for node in _json_ld_nodes(item))
    return nodes


def item_list_urls(html: str) -> list[str]:
    """Detail URLs published in a listing page's schema.org ``ItemList``."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw or "ItemList" not in raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # OCC appends a stray ``;`` to its JobPosting block; the listing's
            # ItemList block is well formed, but a malformed one here is not
            # worth failing the page over -- the next block may still parse.
            continue
        for node in _json_ld_nodes(payload):
            if node.get("@type") != "ItemList":
                continue
            for element in node.get("itemListElement") or []:
                if isinstance(element, dict) and element.get("url"):
                    urls.append(str(element["url"]))
    return urls


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


class OccComMxClient(BrowserScraperClient):
    """Render OCC's listing in Chrome and read each ad from its JSON endpoint."""

    # -- discovery -------------------------------------------------------

    def discover_detail_paths(self, max_jobs: int | None = None) -> list[dict[str, str]]:
        """Walk the rendered listing pages and collect canonical ad URLs."""
        found: list[dict[str, str]] = []
        seen: set[str] = set()
        budget = max_jobs or self._site_config.max_jobs_per_run
        challenge: str | None = None

        for page in range(1, self._site_config.max_pages + 1):
            url = self.listing_url(page)
            try:
                html = self._render(
                    url,
                    self._site_config.listing_ready_selector,
                    self._site_config.listing_wait_seconds,
                )
                self._check_error_page(html, url)
                self._check_challenge(html, url)
            except BrowserChallengeError as exc:
                challenge = str(exc)
                logger.warning("occ_com_mx {}", exc)
                break
            except BrowserFetchError as exc:
                logger.warning("occ_com_mx listing page {} failed: {}", page, exc)
                break

            urls = item_list_urls(html)
            logger.info(
                "occ_com_mx page {}: {} ItemList URL(s) ({} total)",
                page,
                len(urls),
                len(found),
            )
            if not urls:
                break
            for raw in urls:
                link = _normalized_url(raw, self._site_config.base_url)
                if link in seen:
                    continue
                seen.add(link)
                found.append({"url": link, "title": ""})
                if len(found) >= budget:
                    break
            if len(found) >= budget:
                break
            time.sleep(self._site_config.inter_request_delay_seconds)

        if challenge and not found:
            raise OccComMxChallengeError(challenge)
        return found

    # -- detail ----------------------------------------------------------

    def _detail_session(self) -> Any:
        """A browserless session for the ad JSON (no challenge on that host)."""
        from curl_cffi import requests as curl_requests

        profile = self._site_config.impersonate or "chrome"
        return curl_requests.Session(impersonate=profile)

    def _fetch_detail_payload(
        self, session: Any, job_id: str, fallback_url: str
    ) -> tuple[dict[str, Any], str]:
        """Fetch one ad's JSON and return it with the ad's canonical page URL."""
        template = self._site_config.detail_json_url.strip()
        if not template:
            raise OccComMxFetchError("detail_json_url is empty for occ_com_mx")
        endpoint = template.format(id=job_id)
        try:
            response = session.get(
                endpoint,
                timeout=self._site_config.request_timeout_seconds,
                headers={"Accept": "application/json"},
            )
        except Exception as exc:  # noqa: BLE001 - any transport error is a fetch failure
            raise OccComMxFetchError(
                f"detail request failed for offer {job_id}: {exc}"
            ) from exc
        if response.status_code != 200:
            raise OccComMxFetchError(
                f"detail endpoint returned HTTP {response.status_code} for offer {job_id}"
            )
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - a non-JSON body is a fetch failure
            raise OccComMxFetchError(
                f"detail endpoint returned non-JSON for offer {job_id}: {exc}"
            ) from exc
        offer = payload.get("o") if isinstance(payload, dict) else None
        if not isinstance(offer, dict):
            raise OccComMxFetchError(f"detail payload for offer {job_id} has no 'o' object")

        # OCC publishes a hidden salary as smin=smax=0, not as a missing field.
        # The mapper has no zero guard and would render a real "0 - 0" band, so
        # the undisclosed case is turned back into an absent salary here.
        if _as_float(offer.get("smin")) <= 0 and _as_float(offer.get("smax")) <= 0:
            offer["smin"] = None
            offer["smax"] = None

        canonical = str(offer.get("ur") or "").strip()
        page_url = (
            _normalized_url(canonical, self._site_config.base_url)
            if canonical
            else fallback_url
        )
        return payload, page_url

    def _collect(self, budget: int) -> tuple[list[dict], dict[str, str]]:
        records: list[dict] = []
        failures: dict[str, str] = {}
        id_regex = self._site_config.id_url_regex.strip() or _DEFAULT_ID_REGEX

        self.open_session()
        try:
            discovered = self.discover_detail_paths(budget)
            session = self._detail_session()
            for job in discovered[: min(budget, self._site_config.max_detail_pages)]:
                match = re.search(id_regex, job["url"])
                if match is None:
                    failures[job["url"]] = "no offer id in URL"
                    continue
                job_id = match.group(1)
                try:
                    payload, page_url = self._fetch_detail_payload(
                        session, job_id, job["url"]
                    )
                except OccComMxFetchError as exc:
                    failures[job["url"]] = str(exc)
                    logger.warning("occ_com_mx detail fetch failed for {}: {}", job["url"], exc)
                    continue
                html = mapped_json_html(self._site_config, payload, page_url)
                if not html:
                    failures[job["url"]] = "detail_json_map is empty"
                    continue
                offer = payload.get("o") or {}
                records.append(
                    {
                        "job_id": job_id if self._site_config.id_from_url else page_url,
                        "html": html,
                        "url": page_url,
                        "title_hint": str(offer.get("t") or ""),
                        "listing_page": None,
                    }
                )
                time.sleep(self._site_config.inter_request_delay_seconds)
        finally:
            self.close_session()

        logger.info(
            "occ_com_mx: {} record(s), {} failure(s)",
            len(records),
            len(failures),
        )
        return records, failures
