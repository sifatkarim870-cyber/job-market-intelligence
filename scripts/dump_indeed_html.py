"""One-off diagnostic: save a real Indeed search-results page's raw HTML.

This exists for exactly one purpose: getting real, current ground-truth
markup to fix scrapers/indeed/parser.py's selectors against, instead of
guessing again. It does no parsing, no validation, no persistence — it
opens one browser session (same client used by the real pipeline, so the
pacing/session setup is identical to what a real run does), saves the
rendered page source, and quits.

Usage:
    uv run python scripts/dump_indeed_html.py "software engineer" "San Francisco, CA"
    uv run python scripts/dump_indeed_html.py  # defaults to "software engineer" / "Remote"

Writes to: diagnostics/indeed_search_page.html (created if missing)

After running this, search the saved file for "job_seen_beacon" (the
container div parser.py currently keys off) and share back roughly 3000-
4000 characters starting from the first match — enough to see one full
card's actual attribute names (whatever currently holds the title,
company, location, salary) without needing the whole file, which will
contain the full text of real job postings.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from job_market_intel.common.logger import configure_logging
from job_market_intel.scrapers.indeed.client import IndeedClient
from job_market_intel.scrapers.indeed.config import IndeedSettings

OUTPUT_PATH = Path("diagnostics/indeed_search_page.html")


def main() -> int:
    configure_logging(log_dir="logs", console_level="INFO", file_level="DEBUG")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    query = sys.argv[1] if len(sys.argv) > 1 else "software engineer"
    location = sys.argv[2] if len(sys.argv) > 2 else "Remote"

    client = IndeedClient(settings=IndeedSettings())
    logger.info("Opening one Indeed session for {!r} @ {!r}...", query, location)
    client.open_session()
    try:
        html = client.open_search(query, location)
    finally:
        client.close_session()

    OUTPUT_PATH.write_text(html, encoding="utf-8")
    logger.info("Saved {} bytes to {}", len(html), OUTPUT_PATH)
    print(f"\nSaved to: {OUTPUT_PATH.resolve()}")
    print("Search that file for 'job_seen_beacon' and share ~3000-4000 chars from there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
