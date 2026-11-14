"""Client for ADEM Luxembourg's public JobBoard REST API."""

from __future__ import annotations

import concurrent.futures
import json
import ssl
import urllib.request
from typing import Any

from loguru import logger

from .config import AdemLuSettings
from .exceptions import AdemLuFetchError


class AdemLuClient:
    """Fetches job postings from the ADEM Luxembourg CTIE JobBoard."""

    def __init__(self, settings: AdemLuSettings | None = None) -> None:
        self.settings = settings or AdemLuSettings()
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

    def _get_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.settings.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{self.settings.base_url}/en/jobboard.html",
        }

    def fetch_raw_listings(self) -> list[dict[str, Any]]:
        """Fetch all active job postings from the NDJSON stream."""
        url = f"{self.settings.base_url}/ctie/jobboard?id={self.settings.endpoint_id}"
        logger.info("Fetching ADEM listings feed from {}", url)

        req = urllib.request.Request(url, headers=self._get_headers())
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=self.settings.request_timeout_seconds) as resp:
                data = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            raise AdemLuFetchError(f"Failed to fetch ADEM listings feed from {url}: {exc}") from exc

        items: list[dict[str, Any]] = []
        for line in data.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("type") == "items":
                    items.extend(obj.get("items", []))
            except Exception as exc:
                logger.debug("Skipping unparseable NDJSON line from ADEM: {}", exc)

        logger.info("Extracted {} raw job items from ADEM feed.", len(items))
        return items

    def fetch_offer_detail(self, ref: str) -> dict[str, Any] | None:
        """Fetch description and application details for a single offer reference."""
        url = f"{self.settings.base_url}/ctie/jobboard/offer?id={self.settings.endpoint_id}&ref={ref}"
        req = urllib.request.Request(url, headers=self._get_headers())
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=self.settings.request_timeout_seconds) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
        except Exception as exc:
            logger.debug("Failed to fetch detail for ADEM ref {}: {}", ref, exc)
            return None

    def enrich_with_details(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Concurrently enrich the top items with their full description details."""
        if not self.settings.fetch_details:
            return items

        enriched: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.settings.detail_concurrency) as executor:
            future_to_item = {
                executor.submit(self.fetch_offer_detail, str(it.get("ref"))): it
                for it in items
            }
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    detail = future.result()
                    if detail:
                        desc = detail.get("description")
                        if isinstance(desc, list):
                            item["description_text"] = "\n\n".join(desc).strip()
                        elif isinstance(desc, str):
                            item["description_text"] = desc.strip()
                        item["apply_url"] = detail.get("applyUrl")
                except Exception as exc:
                    logger.debug("Error retrieving detail for ADEM job {}: {}", item.get("ref"), exc)
                enriched.append(item)

        return enriched
