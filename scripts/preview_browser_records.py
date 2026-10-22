#!/usr/bin/env python
"""Print the records a browser source would store, so a human can judge them.

Counts are not evidence: a source can "parse 6 records" and have all six be
its own navigation. This prints title, URL and description length for the
first N records of each named source, after the quality gate, without
touching the database.

Usage:
    uv run python scripts/preview_browser_records.py ethiojobs --max-jobs 4
"""

from __future__ import annotations

import argparse
import sys
from urllib.parse import urlparse

from job_market_intel.scrapers.browser_scraper.client import BrowserScraperClient
from job_market_intel.scrapers.browser_scraper.config import (
    BrowserScraperSettings,
    load_browser_site_config,
)
from job_market_intel.scrapers.html_scraper.parser import parse_detail
from job_market_intel.validation.html_scraper_quality import reject_reason

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def preview(code: str, max_jobs: int) -> None:
    settings = BrowserScraperSettings()
    config = load_browser_site_config(code, settings.sites_dir)
    host = urlparse(config.base_url).netloc if config.base_url else ""
    client = BrowserScraperClient(code, settings, config)
    records, failures = client.fetch_raw_jobs(max_jobs=max_jobs)
    print(f"\n=== {code} ({host}) fetched={len(records)} failures={len(failures)}")
    for record in records:
        try:
            job = parse_detail(
                code,
                config,
                record["html"],
                url=record["url"],
                title_hint=record.get("title_hint"),
            )
        except Exception as exc:  # noqa: BLE001 - a preview must not stop on one page
            print(f"  PARSE ERROR {record['url']}: {exc}")
            continue
        reason = reject_reason(
            job.url,
            job.title,
            job.description,
            site_host=host,
            detail_pattern=config.detail_url_pattern,
        )
        verdict = "KEEP" if reason is None else f"DROP ({reason})"
        print(f"  [{verdict}] {job.title!r} :: {job.url} :: desc={len(job.description or '')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="+")
    ap.add_argument("--max-jobs", type=int, default=4)
    args = ap.parse_args()
    for code in args.codes:
        preview(code, args.max_jobs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
