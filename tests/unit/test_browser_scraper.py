"""The browser framework's decision logic, tested without a browser.

Only the parts that decide *something* are here: which URL a listing page is
at, whether a rendered page is a posting or a bot challenge, and whether a
dead browser is worth retrying. The parts that need Chrome are exercised by
the live sweep instead (scripts/test_all_browser_scrapers.py).

Run with:  uv run pytest tests/unit/test_browser_scraper.py -q
"""

from __future__ import annotations

from job_market_intel.scrapers.browser_scraper.client import (
    BrowserScraperClient,
    _is_dead_session,
    _looks_rendered,
    _visible_text,
)
from job_market_intel.scrapers.browser_scraper.config import BrowserSiteConfig
from job_market_intel.scrapers.browser_scraper.exceptions import (
    BrowserChallengeError,
)


def _config(**overrides) -> BrowserSiteConfig:
    base = {
        "source_code": "example",
        "source_name": "Example",
        "country": "Nowhere",
        "base_url": "https://example.com",
        "listing_path": "/jobs",
        "listing_pagination": "?page={page}",
    }
    base.update(overrides)
    return BrowserSiteConfig(**base)


class _StubClient(BrowserScraperClient):
    """A client that never opens a browser."""

    def __init__(self, config: BrowserSiteConfig) -> None:
        self._site_config = config
        self._settings = None
        self._driver = None
        self._detail_pages_visited = 0


def test_listing_url_page_one_is_the_bare_path() -> None:
    client = _StubClient(_config())
    assert client.listing_url(1) == "https://example.com/jobs"


def test_listing_url_paginates_from_page_two() -> None:
    client = _StubClient(_config())
    assert client.listing_url(3) == "https://example.com/jobs?page=3"


def test_listing_url_without_pagination_stays_put() -> None:
    client = _StubClient(_config(listing_pagination=""))
    assert client.listing_url(4) == "https://example.com/jobs"


def test_a_page_that_links_a_recaptcha_script_is_not_a_challenge() -> None:
    """The word "captcha" in a script tag is not a bot challenge.

    Matching the raw HTML rejected jobberman.com, a board that works: its
    page includes a reCAPTCHA script on every listing. The check has to be on
    the visible text.
    """
    html = """
    <html><head><script src="https://www.google.com/recaptcha/api.js"></script></head>
    <body><h1>Accountant</h1><div class="description">We are hiring</div></body></html>
    """
    client = _StubClient(_config())
    client._check_challenge(html, "https://example.com/jobs")  # must not raise


def test_a_visible_captcha_is_a_challenge() -> None:
    html = """
    <html><body><div class="captcha">Please complete the captcha</div></body></html>
    """
    client = _StubClient(_config())
    try:
        client._check_challenge(html, "https://example.com/jobs")
    except BrowserChallengeError as exc:
        assert "captcha" in str(exc)
    else:  # pragma: no cover - the call must raise
        raise AssertionError("a visible captcha must be treated as a challenge")


def test_a_cloudflare_marker_in_the_markup_is_a_challenge() -> None:
    html = '<html><head><script src="/cdn-cgi/challenge-platform/x"></script></head></html>'
    client = _StubClient(_config())
    try:
        client._check_challenge(html, "https://example.com/jobs")
    except BrowserChallengeError:
        return
    raise AssertionError("the challenge platform marker must be treated as a challenge")


def test_a_rendered_page_has_a_heading_and_text() -> None:
    body = "<h1>Senior Engineer</h1><p>" + ("We are hiring. " * 400) + "</p>"
    html = f"<html><body>{body}</body></html>"
    assert _looks_rendered(html) is True


def test_a_client_side_shell_is_not_rendered() -> None:
    """A shell has navigation, a script bundle and no body text."""
    html = "<html><body><nav><a href='/about'>About</a></nav></body></html>"
    assert _looks_rendered(html) is False


def test_visible_text_drops_scripts() -> None:
    html = "<html><body><script>var captcha = 1;</script><p>Real text</p></body></html>"
    text = _visible_text(html)
    assert "real text" in text
    assert "var captcha" not in text


def test_a_dead_browser_is_recognised() -> None:
    class NoSuchWindowException(Exception):
        pass

    class TargetClosedError(Exception):
        pass

    class SomeOtherError(Exception):
        pass

    assert _is_dead_session(NoSuchWindowException("no such window")) is True
    assert _is_dead_session(TargetClosedError("target window already closed")) is True
    assert _is_dead_session(SomeOtherError("nope")) is False
