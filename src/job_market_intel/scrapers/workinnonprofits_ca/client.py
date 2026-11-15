"""HTTP client for WorkInNonProfits (Canada) feeds and detail pages."""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from loguru import logger

from .config import WorkInNonProfitsSettings
from .exceptions import WorkInNonProfitsAPIError
from .models import DiscoveredJobItem, RawWorkInNonProfitsJob

_ID_RE = re.compile(r"/view/([0-9]{4,8})")


class WorkInNonProfitsClient:
    """Client for discovering postings from WorkInNonProfits RSS feed and fetching detail HTML."""

    def __init__(self, settings: WorkInNonProfitsSettings | None = None) -> None:
        self.settings = settings or WorkInNonProfitsSettings()

    def _fetch(self, url: str) -> str:
        """Fetch content over HTTP with configured User-Agent and timeout."""
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.settings.request_timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise WorkInNonProfitsAPIError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise WorkInNonProfitsAPIError(f"Network error fetching {url}: {exc.reason}") from exc
        except Exception as exc:
            raise WorkInNonProfitsAPIError(f"Unexpected error fetching {url}: {exc}") from exc

    def fetch_discovered_jobs(self) -> list[DiscoveredJobItem]:
        """Fetch the XML feed and parse out DiscoveredJobItem records."""
        logger.info("Fetching WorkInNonProfits RSS feed from {}", self.settings.feed_url)
        content = self._fetch(self.settings.feed_url)

        items: list[DiscoveredJobItem] = []
        try:
            root = ET.fromstring(content)
            for el in root.findall(".//item"):
                title = el.findtext("title", "").strip()
                link = el.findtext("link", "").strip()
                desc = el.findtext("description", "").strip()
                pub_date = el.findtext("pubDate", "").strip()

                id_m = _ID_RE.search(link)
                job_id = id_m.group(1) if id_m else ""
                if not job_id or not title or not link:
                    continue

                emp_m = re.search(r"<b>Employer:</b>\s*([^<]+)", desc)
                employer = emp_m.group(1).strip() if emp_m else None

                loc_m = re.search(r"<b>Location:</b>\s*([^<]+)", desc)
                location = loc_m.group(1).strip() if loc_m else None

                type_m = re.search(r"<b>Type:</b>\s*([^<]+)", desc)
                type_info = type_m.group(1).strip() if type_m else None

                dead_m = re.search(r"<b>Deadline:</b>\s*([^<]+)", desc)
                deadline = dead_m.group(1).strip() if dead_m else None

                items.append(
                    DiscoveredJobItem(
                        url=link,
                        job_id=job_id,
                        title=title,
                        employer=employer,
                        location=location,
                        type_info=type_info,
                        deadline=deadline,
                        pub_date=pub_date,
                    )
                )
        except Exception as exc:
            logger.warning("Failed to parse RSS feed: {}. Falling back to Atom feed.", exc)
            try:
                atom_content = self._fetch(self.settings.atom_feed_url)
                atom_root = ET.fromstring(atom_content)
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                for entry in atom_root.findall(".//atom:entry", ns):
                    title = entry.findtext("atom:title", "", ns).strip()
                    link_el = entry.find("atom:link", ns)
                    link = link_el.get("href", "").strip() if link_el is not None else ""
                    id_m = _ID_RE.search(link)
                    job_id = id_m.group(1) if id_m else ""
                    if job_id and title and link:
                        items.append(
                            DiscoveredJobItem(
                                url=link,
                                job_id=job_id,
                                title=title,
                            )
                        )
            except Exception as atom_exc:
                logger.error("Failed to parse Atom feed as well: {}", atom_exc)

        logger.info("Discovered {} active vacancies from WorkInNonProfits feed.", len(items))
        return items

    def fetch_job_detail(self, item: DiscoveredJobItem) -> RawWorkInNonProfitsJob | None:
        """Fetch detail page HTML for a single job."""
        try:
            html_doc = self._fetch(item.url)
            return RawWorkInNonProfitsJob(
                item=item,
                html_content=html_doc,
            )
        except WorkInNonProfitsAPIError as exc:
            logger.warning("Failed to fetch detail for job {}: {}", item.job_id, exc)
            return None

    def fetch_all_details(
        self, items: list[DiscoveredJobItem]
    ) -> list[RawWorkInNonProfitsJob]:
        """Fetch detail pages for a batch of jobs with rate limiting."""
        raw_jobs: list[RawWorkInNonProfitsJob] = []
        logger.info("Fetching details for {} WorkInNonProfits postings...", len(items))
        for idx, item in enumerate(items, 1):
            raw = self.fetch_job_detail(item)
            if raw is not None:
                raw_jobs.append(raw)
            if self.settings.rate_limit_delay > 0 and idx < len(items):
                time.sleep(self.settings.rate_limit_delay)
        logger.info("Successfully fetched {} WorkInNonProfits detail pages.", len(raw_jobs))
        return raw_jobs
