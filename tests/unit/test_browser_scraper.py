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


JOB_POSTING_PAGE = """
<html><body><h1>Accounts Assistant</h1>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "JobPosting",
 "title": "Accounts Assistant",
 "description": "<p>Maintain ledgers and reconcile bank statements.</p>",
 "datePosted": "2026-10-24",
 "hiringOrganization": {"@type": "Organization", "name": "Acme LLC"},
 "jobLocation": {"@type": "Place",
                 "address": {"@type": "PostalAddress", "addressLocality": "Dubai"}}}
</script></body></html>
"""


def test_detail_html_is_left_alone_without_json_ld() -> None:
    client = _StubClient(_config())
    assert client._detail_html(JOB_POSTING_PAGE, "https://example.com/jobs/1") == JOB_POSTING_PAGE


def test_detail_json_ld_is_mapped_from_the_rendered_page() -> None:
    """The browser framework inherited ``detail_json_ld`` but ignored it.

    A rendered page is already in hand, so mapping it needs no second fetch;
    before this the option silently did nothing and the posting was parsed
    from markup that carried no body.
    """
    client = _StubClient(
        _config(
            detail_json_ld=True,
            detail_json_map={
                "title": "title",
                "company": "hiringOrganization.name",
                "location": "jobLocation.address.addressLocality",
                "description": "description",
                "posted_date": "datePosted",
            },
        )
    )

    html = client._detail_html(JOB_POSTING_PAGE, "https://example.com/jobs/1")

    assert "<h1>Accounts Assistant</h1>" in html
    assert "Acme LLC" in html
    assert "Dubai" in html
    assert "reconcile bank statements" in html
    assert "2026-10-24" in html


def test_detail_page_without_json_ld_falls_back_to_the_markup() -> None:
    """Some ads on a board publish no JobPosting block; the CSS selectors do.

    dubizzle's older ads have no block at all. Raising here would discard an ad
    whose rendered page still carries title, employer and body; the quality
    gate is what rejects a page that truly has nothing.
    """
    page = "<html><body><h1>No block here</h1></body></html>"
    client = _StubClient(_config(detail_json_ld=True, detail_json_map={"title": "title"}))

    assert client._detail_html(page, "https://example.com/jobs/1") == page


class _FakeDriver:
    """Just enough driver for the load-more and settle paths."""

    def __init__(self, rounds: list[list[str]], page_source: str = "<html>loaded</html>"):
        self._rounds = list(rounds)
        self.clicked: list[str] = []
        self.scripts: list[str] = []
        self.page_source = page_source

    def find_elements(self, by: str, selector: str) -> list[str]:
        return self._rounds.pop(0) if self._rounds else []

    def execute_script(self, script: str, *args):
        self.scripts.append(script)
        if args:
            self.clicked.append(args[0])
        return None


def _no_sleep(monkeypatch) -> list[float]:
    calls: list[float] = []
    monkeypatch.setattr("job_market_intel.scrapers.browser_scraper.client.time.sleep", calls.append)
    return calls


def test_load_more_is_pressed_until_the_control_disappears(monkeypatch) -> None:
    """Töötukassa renders 20 ads and waits for "Laadi veel" (2026-10-28).

    The control is pressed through ``arguments[0].click()`` because a plain
    Selenium click on the wrapper ``[role='button']`` left the listing at 20
    links while the inner ``span.load-more`` doubled it.
    """
    sleeps = _no_sleep(monkeypatch)
    client = _StubClient(
        _config(
            listing_more_selector="tk-load-more span.load-more",
            listing_more_clicks=3,
            listing_more_pause_seconds=7.0,
        )
    )
    driver = _FakeDriver([["first"], ["second"], []])
    client._driver = driver

    client._click_load_more()

    assert driver.clicked == ["first", "second"]
    assert driver.scripts == ["arguments[0].click();", "arguments[0].click();"]
    assert sleeps == [7.0, 7.0]


def test_load_more_stops_at_the_declared_click_budget(monkeypatch) -> None:
    _no_sleep(monkeypatch)
    client = _StubClient(_config(listing_more_selector=".more", listing_more_clicks=2))
    driver = _FakeDriver([["a"], ["b"], ["c"], ["d"]])
    client._driver = driver

    client._click_load_more()

    assert driver.clicked == ["a", "b"]


def test_load_more_does_nothing_when_the_site_declares_none() -> None:
    client = _StubClient(_config())
    driver = _FakeDriver([["a"]])
    client._driver = driver

    client._click_load_more()

    assert driver.clicked == []
    assert driver.scripts == []


def test_a_failing_load_more_click_does_not_lose_the_listing(monkeypatch) -> None:
    """A stale element is a short listing, not a failed run."""
    _no_sleep(monkeypatch)
    client = _StubClient(_config(listing_more_selector=".more", listing_more_clicks=2))

    class _BrokenDriver(_FakeDriver):
        def execute_script(self, script: str, *args):
            raise RuntimeError("stale element reference")

    driver = _BrokenDriver([["a"], ["b"]])
    client._driver = driver

    client._click_load_more()  # must not raise


def test_detail_settle_waits_before_reading_the_page(monkeypatch) -> None:
    """A detail selector is only the first fragment on an Angular page.

    Measured on Töötukassa (2026-10-28): the title was in the DOM while the
    employer block and requirements were still rendering, so reading at the
    first match stored an employer of "Tööülesanded" and a half-length body.
    """
    sleeps = _no_sleep(monkeypatch)
    client = _StubClient(_config(detail_settle_seconds=6.0))
    client._driver = _FakeDriver([], page_source="<html>finished</html>")

    assert client._settle_then_read() == "<html>finished</html>"
    assert sleeps == [6.0]


def test_detail_settle_of_zero_reads_immediately(monkeypatch) -> None:
    sleeps = _no_sleep(monkeypatch)
    client = _StubClient(_config())
    client._driver = _FakeDriver([], page_source="<html>finished</html>")

    assert client._settle_then_read() == "<html>finished</html>"
    assert sleeps == []
