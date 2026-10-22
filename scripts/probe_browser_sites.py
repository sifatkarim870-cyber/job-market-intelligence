#!/usr/bin/env python
"""Render candidate URLs in Chrome and report what each one actually shows.

A plain-HTTP sweep says "no job links" for a board that is simply a
client-side app, and for a board that is serving a bot challenge, and for a
board that is dead. Those are three different problems with three different
fixes, and the HTTP sweep cannot tell them apart. This probe can: it opens
each URL in a real browser and reports the rendered title, the anchor count,
whether a challenge was served, and a sample of the links that were there.

Usage:
    uv run python scripts/probe_browser_sites.py --url https://ethiojobs.com/
    uv run python scripts/probe_browser_sites.py --config ethiojobs
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CHALLENGE_MARKERS = (
    "just a moment",
    "checking your browser",
    "pardon our interruption",
    "enable javascript and cookies to continue",
    "verify you are human",
    "unusual traffic",
    "access denied",
    "安全验证",
    "请输入验证码",
)


def _posting_shaped(url: str) -> bool:
    """A URL that looks like one posting rather than a section or a category.

    Same vocabulary the quality gate uses, so what the probe calls a posting is
    what the scraper would keep.
    """
    from job_market_intel.validation.html_scraper_quality import (
        SECTION_FRAGMENTS,
        SECTION_SEGMENTS,
        has_job_keyword,
    )

    path = urlparse(url).path.lower()
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return False
    for fragment in SECTION_FRAGMENTS:
        if fragment in path:
            return False
    if parts[-1] in SECTION_SEGMENTS:
        return False
    if parts[-1].endswith(("-jobs", "-job", "_jobs")):
        return False
    return has_job_keyword(path)


def probe(url: str, wait_seconds: int, driver, scrolls: int = 0) -> dict:
    driver.get(url)
    import time

    time.sleep(wait_seconds)
    for _ in range(scrolls):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
    html = driver.page_source
    lowered = html[:200000].lower()
    challenge = next((marker for marker in CHALLENGE_MARKERS if marker in lowered), None)

    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.find_all("a", href=True)
    title = soup.title.get_text(strip=True) if soup.title else ""
    host = urlparse(url).netloc
    prefixes = Counter()
    for anchor in anchors[:400]:
        path = urlparse(urljoin(url, anchor["href"])).path
        parts = [part for part in path.split("/") if part]
        prefixes[parts[0] if parts else ""] += 1

    return {
        "url": url,
        "title": title,
        "anchors": len(anchors),
        "challenge": challenge,
        "bytes": len(html),
        "prefixes": prefixes.most_common(8),
        "samples": [
            (urljoin(url, a["href"]), a.get_text(" ", strip=True)[:60]) for a in anchors[:12]
        ],
        "postings": [
            (urljoin(url, a["href"]), a.get_text(" ", strip=True)[:70])
            for a in anchors
            if _posting_shaped(urljoin(url, a["href"]))
        ],
        "host": host,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", action="append", default=[], help="URL to probe")
    ap.add_argument("--wait", type=int, default=8, help="Seconds to wait after load")
    ap.add_argument("--scrolls", type=int, default=0, help="Scroll the page N times before reading")
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args()

    if not args.url:
        print("nothing to probe")
        return 1

    from seleniumbase import Driver

    proxy = os.environ.get("BROWSER_SCRAPER_PROXY", "").strip()
    driver = None
    for url in args.url:
        # A fresh browser per URL: one slow board must not take the rest of the
        # batch down with it, and the session died twice in a long batch.
        if driver is None:
            driver = Driver(
                uc=True,
                headless2=not args.headful,
                page_load_strategy="eager",
                **({"proxy": proxy} if proxy else {}),
            )
        try:
            result = probe(url, args.wait, driver, scrolls=args.scrolls)
        except Exception as exc:  # noqa: BLE001
            print(f"\n### {url}\n  FAILED: {exc}")
            try:
                driver.quit()
            except Exception:  # noqa: BLE001
                pass
            driver = None
            continue
        print(f"\n### {result['url']}")
        print(f"  title:    {result['title'][:80]}")
        print(f"  anchors:  {result['anchors']}  bytes: {result['bytes']}")
        print(f"  challenge: {result['challenge'] or 'none'}")
        print("  path prefixes:")
        for prefix, count in result["prefixes"]:
            print(f"     {count:4} {prefix}")
        print("  sample links:")
        for href, text in result["samples"]:
            print(f"     {text!r} -> {href[:110]}")
        print(f"  posting-shaped links: {len(result['postings'])}")
        deep = [
            entry
            for entry in result["postings"]
            if len(urlparse(entry[0]).path.strip("/").split("/")) >= 3
        ]
        print(f"  deep links (3+ path segments): {len(deep)}")
        for href, text in (deep or result["postings"])[:20]:
            print(f"     {text!r} -> {href[:110]}")
    if driver is not None:
        driver.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
