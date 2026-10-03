"""Indeed-specific configuration.

Unlike RemoteOK/Remotive/WWR's config classes, most of what's here isn't
"how to reach the API" — it's the confirmed pacing/session-cap decisions
from the project's own scoping conversation for this scraper: slow enough,
and bounded enough per session, that a years-long, never-ending crawl stays
unremarkable rather than fast. See client.py's module docstring for how
these values are actually used.

Every setting has a sensible default from that scoping conversation, so the
scraper works out-of-the-box with no ``.env`` entries at all. Add entries
prefixed with ``INDEED_`` to override a default, e.g.:

    INDEED_MAX_SEARCH_PAGES_PER_SESSION=3
    INDEED_HEADLESS=false
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IndeedSettings(BaseSettings):
    """Configuration for the Indeed scraper, loaded from environment/.env.

    Attributes:
        base_url: Indeed's site root. Search URLs are built as
            ``{base_url}/jobs?q=...&l=...``; Indeed itself redirects the
            browser to its own canonical "pretty" URL and pagination
            follows the "next" link found in the rendered page, never a
            hand-built ``?start=N`` URL (confirmed decision — see
            client.py).
        headless: Whether the browser runs without a visible window.
            Defaults to False: headless mode is itself a documented
            fingerprinting signal, and this project already accepted the
            larger tradeoff (a visible/virtual-display browser process)
            in exchange for not looking like a script. Override to True
            only on infrastructure where a virtual display (e.g. Xvfb) is
            already handling this the same way.
        page_action_min_wait_seconds / page_action_max_wait_seconds:
            Randomized delay window applied before every navigation or
            click. A fixed delay is itself a detectable pattern — the
            randomization matters as much as the average.
        long_pause_every_n_pages: After this many search-result pages in
            one session, take a much longer pause (see
            ``long_pause_min_seconds``/``long_pause_max_seconds``) before
            continuing, breaking up the request rhythm further.
        long_pause_min_seconds / long_pause_max_seconds: Randomized
            duration of that longer pause.
        max_search_pages_per_session: Hard cap on search-result pages
            visited in one browser session, regardless of how many the
            query actually has. The session closes cleanly once this (or
            ``max_detail_pages_per_session``) is hit; the query queue
            (``ops.scrape_query_queue``) picks up where it left off next
            run.
        max_detail_pages_per_session: Hard cap on individual job-detail
            (``/viewjob?``) pages visited in one session.
        max_consecutive_failures: If this many page loads/parses fail in a
            row (not total across the session — *in a row*), the session
            is treated as blocked and stops immediately. See
            ``exceptions.IndeedBlockedError``.
        page_load_timeout_seconds: Selenium page-load timeout.
        session_start_timeout_seconds: Bound on the session *handshake*
            (see the field description) — the one timeout that has to be
            generous on slow machines, since nothing has happened yet that
            ``page_load_timeout_seconds`` could bound.
        request_user_agent: Not sent as a raw HTTP header the way
            ``common/http_client.py``'s scrapers do — Selenium controls
            the real browser's own UA. Kept here anyway as the value
            passed to the driver's UA-override option, so it's a single
            documented setting rather than buried in client.py.
    """

    model_config = SettingsConfigDict(
        env_prefix="INDEED_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_url: str = "https://www.indeed.com"
    headless: bool = False

    uc_enabled: bool = Field(
        default=True,
        description=(
            "Whether seleniumbase launches Chrome in UC (undetected) mode. "
            "True preserves this project's anti-fingerprinting decision "
            "(plain Selenium is commonly blocked on Indeed). The self-hosted "
            "CI runner is a documented exception: UC mode there hangs on "
            "session start / page load against that VM's Chrome, while the "
            "plain seleniumbase driver works — so the Indeed CI step sets "
            "INDEED_UC_ENABLED=false (see .github/workflows/scrape.yml)."
        ),
    )

    page_action_min_wait_seconds: float = 4.0
    page_action_max_wait_seconds: float = 9.0

    long_pause_every_n_pages: int = 5
    long_pause_min_seconds: float = 45.0
    long_pause_max_seconds: float = 90.0

    max_search_pages_per_session: int = 5
    max_detail_pages_per_session: int = 60
    max_consecutive_failures: int = 3

    items_per_run: int = Field(
        default=10,
        description=(
            "How many queue rows one pipeline run claims and works, each "
            "as its own bounded, paced browser session. It was 1 when the "
            "queue had a handful of rows; the queue is now seeded with "
            "~21,000 combinations (every country x a broad job-title set), "
            "and one combination per every-12-hours run made no meaningful "
            "progress against it. 10 per run keeps one invocation inside the "
            "scheduled job's timeout (ten individually-paced sessions of up "
            "to 5 search + 60 detail pages each) while giving real coverage. "
            "INDEED_ITEMS_PER_RUN overrides it."
        ),
    )

    page_load_timeout_seconds: float = 30.0

    session_start_timeout_seconds: float = Field(
        default=300.0,
        description=(
            "How long to wait for the browser session handshake itself (the "
            "WebDriver NEW_SESSION call) before giving up on open_session(). "
            "This is a different thing from page_load_timeout_seconds, which "
            "only bounds a page once a session exists: a cold Chrome on a "
            "low-memory VM can spend the best part of a minute just reaching "
            "the point where it can answer that first request, which is well "
            "past selenium's own built-in 120s HTTP read timeout for driver "
            "calls. Only applies to the UC-off path; seleniumbase's Driver "
            "has no equivalent knob. INDEED_SESSION_START_TIMEOUT_SECONDS "
            "overrides it."
        ),
    )

    request_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
