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

# Default Indeed domain. Country domains (uk/de/in/...) are what make
# worldwide coverage actually return *local* results: the US portal ignores
# the foreign part of a location string and serves US jobs regardless, which
# we confirmed live -- q=x&l=Tokyo on www.indeed.com returned jobs in Phoenix,
# AZ. Each country domain + its own location string returns real local jobs
# (uk.indeed.com/London, de.indeed.com/Germany, in.indeed.com/India -- all
# verified returning country-local results from the same residential IP).
_DEFAULT_BASE_URL = "https://www.indeed.com"

# Location alias -> Indeed country domain. Aliases are matched against the
# final comma-separated segment of the location, lowercased, so both
# "London, UK" (-> uk) and "Berlin, Germany" (-> de) work while US
# locations like "Austin, TX" fall through to the US default below. This is
# deliberately a flat lookup rather than a parsed "country object": the queue
# only ever carries free-text locations.
_COUNTRY_DOMAINS: dict[str, str] = {
    # North America
    "us": "https://www.indeed.com", "usa": "https://www.indeed.com",
    "united states": "https://www.indeed.com", "canada": "https://ca.indeed.com",
    # Europe
    "uk": "https://uk.indeed.com", "united kingdom": "https://uk.indeed.com",
    "ireland": "https://ie.indeed.com", "germany": "https://de.indeed.com",
    "france": "https://fr.indeed.com", "spain": "https://es.indeed.com",
    "italy": "https://it.indeed.com", "netherlands": "https://nl.indeed.com",
    "belgium": "https://be.indeed.com", "austria": "https://at.indeed.com",
    "switzerland": "https://ch.indeed.com", "sweden": "https://se.indeed.com",
    "norway": "https://no.indeed.com", "denmark": "https://dk.indeed.com",
    "finland": "https://fi.indeed.com", "poland": "https://pl.indeed.com",
    "portugal": "https://pt.indeed.com", "greece": "https://gr.indeed.com",
    "czech republic": "https://cz.indeed.com", "czechia": "https://cz.indeed.com",
    "romania": "https://ro.indeed.com", "hungary": "https://hu.indeed.com",
    "croatia": "https://hr.indeed.com", "bulgaria": "https://bg.indeed.com",
    "luxembourg": "https://lu.indeed.com", "ukraine": "https://ua.indeed.com",
    # Asia / Oceania
    "india": "https://in.indeed.com", "japan": "https://jp.indeed.com",
    "china": "https://cn.indeed.com", "singapore": "https://sg.indeed.com",
    "hong kong": "https://hk.indeed.com", "malaysia": "https://my.indeed.com",
    "indonesia": "https://id.indeed.com", "philippines": "https://ph.indeed.com",
    "thailand": "https://th.indeed.com", "vietnam": "https://vn.indeed.com",
    "south korea": "https://kr.indeed.com", "taiwan": "https://tw.indeed.com",
    "pakistan": "https://pk.indeed.com",
    "australia": "https://au.indeed.com", "new zealand": "https://nz.indeed.com",
    # Middle East / Africa / LatAm
    "uae": "https://ae.indeed.com", "saudi arabia": "https://sa.indeed.com",
    "egypt": "https://eg.indeed.com", "south africa": "https://za.indeed.com",
    "nigeria": "https://ng.indeed.com",
    "mexico": "https://mx.indeed.com", "brazil": "https://br.indeed.com",
    "argentina": "https://ar.indeed.com", "chile": "https://cl.indeed.com",
    "colombia": "https://co.indeed.com", "peru": "https://pe.indeed.com",
}

# US state codes, so "Austin, TX" and "Remote, NY" route to the US site.
_US_STATE_CODES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy", "dc",
}


def base_url_for_location(location_text: str) -> str:
    """Picks the Indeed country domain for a queue location string.

    "Remote" (the US default) and US city/state pairs route to the US site;
    a trailing country segment routes to that country's site; anything else
    falls back to the US default. Never raises -- an unknown location just
    gets the US portal, which is harmless (it's what every row got before).
    """
    cleaned = location_text.strip().lower()
    if not cleaned:
        return _DEFAULT_BASE_URL
    if cleaned in ("remote", "anywhere", "worldwide"):
        return _DEFAULT_BASE_URL

    parts = [p.strip() for p in cleaned.split(",")]
    last = parts[-1]
    # "Austin, TX" style: trailing segment is a US state code.
    if last in _US_STATE_CODES:
        return _DEFAULT_BASE_URL
    if last in _COUNTRY_DOMAINS:
        return _COUNTRY_DOMAINS[last]

    # "Berlin, Germany" already handled; also try the whole string, so
    # a bare "Germany" row matches even without a trailing-segment split.
    if cleaned in _COUNTRY_DOMAINS:
        return _COUNTRY_DOMAINS[cleaned]
    return _DEFAULT_BASE_URL


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
        session_start_attempts: Launches to try before the row is written
            off as failed.
        session_start_retry_wait_seconds: Base pause between those attempts.
        request_user_agent: Not sent as a raw HTTP header the way
            ``common/http_client.py``'s scrapers do — Selenium controls
            the real browser's own UA. Kept here anyway as the value
            passed to the driver's UA-override option, so it's a single
            documented setting rather than buried in client.py.
        proxy_server / proxy_username / proxy_password: Optional forward
            proxy for the browser session. Set all three when the proxy needs
            basic auth; the client supplies credentials through a generated
            onAuthRequired extension, because Chrome ignores credentials
            passed in the --proxy-server flag.
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

    session_start_attempts: int = Field(
        default=3,
        description=(
            "How many times open_session() tries to start a browser before "
            "giving up on a queue row. More than one because on a small VM a "
            "launch can fail on available memory rather than on anything "
            "wrong with the request: on the CI runner the identical Chrome "
            "flag set failed at 127s in one run and started in 49s in "
            "another. UC-off path only — seleniumbase's Driver does its own "
            "thing and is left alone. INDEED_SESSION_START_ATTEMPTS "
            "overrides it."
        ),
    )

    session_start_retry_wait_seconds: float = Field(
        default=15.0,
        description=(
            "Base pause between session-start attempts, multiplied by the "
            "attempt number so a retry doesn't immediately re-collide with "
            "whatever was still holding memory. "
            "INDEED_SESSION_START_RETRY_WAIT_SECONDS overrides it."
        ),
    )

    request_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    proxy_server: str | None = Field(
        default=None,
        description=(
            "Optional forward proxy for the browser, e.g. 'http://host:port' or "
            "'socks5://host:port'. Empty means no proxy. This exists because "
            "Indeed's edge (Cloudflare) refuses the self-hosted CI runner's "
            "egress IP outright: measured from 172.197.177.36, every browser "
            "configuration -- plain headless, seleniumbase UC headless, UC "
            "headful under Xvfb, and a stock Chrome with no automation at all "
            "-- was served Cloudflare's managed challenge, which never "
            "cleared. The same code and browser config from a residential IP "
            "returns a full results page. A proxy changes the egress IP and "
            "nothing else."
        ),
    )

    proxy_username: str | None = Field(
        default=None,
        description=(
            "Username for proxy basic auth, if the proxy requires it. Chrome "
            "will not take credentials in --proxy-server, so the client "
            "generates a small onAuthRequired extension when this and "
            "proxy_password are both set."
        ),
    )

    proxy_password: str | None = Field(
        default=None,
        description="Password for proxy basic auth, if the proxy requires it."
    )
