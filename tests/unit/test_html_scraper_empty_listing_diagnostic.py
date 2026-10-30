"""An empty listing page must explain itself in the log.

On 2026-10-30 the HTML group reported `listing page 1: 0 job link(s)` for
lucru_md from the runner, while the same URL returned 40 links from a laptop.
That one line cannot distinguish "the board changed its markup" from "the edge
served the runner a challenge page", so the first fix attempt was guesswork.

``_warn_empty_listing`` now logs the page title, size, a text sample, and any
known anti-bot marker. These tests pin that diagnostic.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.scrapers.html_scraper.client import HtmlScraperClient
from job_market_intel.scrapers.html_scraper.config import SiteConfig

CHALLENGE_PAGE = """
<html><head><title>Just a moment...</title></head>
<body><p>Checking your browser before accessing lucru.md.</p>
<p>Enable JavaScript and cookies to continue.</p></body></html>
"""

PLAIN_PAGE = """
<html><head><title>Lucru.md</title></head>
<body><p>No vacancies right now.</p></body></html>
"""


def _client() -> HtmlScraperClient:
    return HtmlScraperClient(
        source_code="unit_test",
        site_config=SiteConfig(
            source_code="unit_test",
            source_name="Unit test board",
            country="Nowhere",
            base_url="https://example.invalid",
        ),
    )


def _capture_warnings() -> tuple[list[str], int]:
    messages: list[str] = []
    sink_id = logger.add(
        lambda message: messages.append(message.record["message"]),
        level="WARNING",
        format="{message}",
    )
    return messages, sink_id


def test_challenge_page_names_the_marker() -> None:
    messages, sink_id = _capture_warnings()
    try:
        _client()._warn_empty_listing(CHALLENGE_PAGE)
    finally:
        logger.remove(sink_id)

    assert len(messages) == 1
    line = messages[0]
    assert "Just a moment..." in line
    assert "checking your browser" in line.lower().replace("challenge_marker=", "")
    assert "challenge_marker='just a moment'" in line
    assert "bytes=" in line


def test_ordinary_empty_page_has_no_marker_claim() -> None:
    messages, sink_id = _capture_warnings()
    try:
        _client()._warn_empty_listing(PLAIN_PAGE)
    finally:
        logger.remove(sink_id)

    assert len(messages) == 1
    assert "challenge_marker" not in messages[0]
    assert "Lucru.md" in messages[0]
    assert "No vacancies right now." in messages[0]
