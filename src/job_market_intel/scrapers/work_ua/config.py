"""Configuration for the work.ua (Ukraine) scraper.

work.ua is Ukraine's largest job board (about 86,500 live vacancies on
2026-11-28, 6,208 listing pages of roughly 14 ads each). It is a
server-rendered HTML board, but it is not reachable with plain ``requests``:
its Cloudflare edge answers HTTP 403 with work.ua's own
"доступ до сайту тимчасово заборонено" page to every Chrome/Edge
``curl_cffi`` profile, while a Safari or Firefox profile gets HTTP 200. This
package is therefore a bespoke client that speaks through ``curl_cffi`` with
``safari17_0`` (falling back to ``firefox133``/``safari18_0`` if a profile is
ever refused), keeps TLS verification ON (no ``verify=False``), and uses no
key, login, cookie or proxy.

**robots.txt** (``https://www.work.ua/robots.txt``, HTTP 200, 4,663 bytes).
It has three groups -- ``Linguee``, ``*`` and ``ClaudeBot``. Only the ``*``
group binds this client. It disallows private/account paths, ``*.php``,
``/api/v*/poll/``, ``/api/v*/jobs/*/phone-click/`` and a long list of
unrelated query parameters (``employment``, ``salaryfrom``, ``sort``,
``regionId``, ...); the pagination parameter used here, ``page``, is not
listed, so ``/jobs/?page=N`` and the ad pages ``/jobs/<id>/`` are allowed.
The ``Crawl-delay: 2`` line sits inside the ``ClaudeBot`` group, not the
``*`` group, so it does not bind us; a polite half-second gap is kept anyway.

**Discovery.** ``GET /jobs/?page=N`` (page 1 must carry the query -- the bare
``/jobs/`` path serves a JavaScript landing shell with no cards) returns 14
cards, each an ``<a href="/jobs/<id>/">``. Pages are walked in order until the
row budget is met. The listing is the board's own default order, which mixes
newly activated and bumped ads, so a capped run sees the most recently active
ads first.

**Detail.** ``GET /jobs/<id>/`` is server-rendered. The title is
``#h1-name``; the employer is the ``data-company-name`` attribute; salary,
address and schedule are ``<li>`` rows anchored by an icon ``<span title=...>``
(``Зарплата`` / ``Адреса роботи`` / ``Графік роботи``); the body is
``#job-description``; and ``data-online-at`` carries the ad's activation
timestamp in ISO-8601 with a ``+02:00`` offset.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkUaSettings(BaseSettings):
    """Runtime configuration for the work.ua (Ukraine) scraper."""

    model_config = SettingsConfigDict(
        env_prefix="WORK_UA_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(default="https://www.work.ua", description="Site root.")
    listing_path: str = Field(default="/jobs/", description="Listing path (needs ?page=N).")
    listing_pagination: str = Field(default="?page={page}", description="Listing pager template.")
    detail_url_template: str = Field(
        default="{base_url}/jobs/{job_id}/", description="Per-ad page URL template."
    )
    max_jobs_per_run: int = Field(
        default=200,
        ge=1,
        description="Cap on ad pages fetched and postings persisted in one run.",
    )
    listing_page_size: int = Field(
        default=14,
        ge=1,
        description="Ads per listing page; used only to size the page budget.",
    )
    max_pages_scanned: int = Field(
        default=2000,
        ge=1,
        description="Hard ceiling on listing pages walked in one run.",
    )
    fetch_details: bool = Field(
        default=True,
        description="Fetch each ad's detail page. A run without it yields no descriptions.",
    )

    #: Cloudflare refuses every Chrome/Edge profile on this site while a Safari
    #: profile is served normally. The fallbacks are tried, in order, only when
    #: the primary profile answers HTTP 403.
    impersonate: str = Field(
        default="safari17_0", description="curl_cffi impersonation profile for the primary try."
    )
    impersonate_fallbacks: list[str] = Field(
        default_factory=lambda: ["firefox133", "safari18_0"],
        description="Profiles retried when the primary one is refused with HTTP 403.",
    )
    user_agent: str = Field(
        default="",
        description="Optional explicit User-Agent; empty lets the impersonation profile set it.",
    )
    request_timeout_seconds: float = Field(default=45.0, gt=0)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: No Crawl-delay binds the ``*`` group (the site's ``Crawl-delay: 2`` is in
    #: the ClaudeBot group). Half a second keeps a 200-ad run polite and quick.
    inter_request_delay_seconds: float = Field(default=0.5, ge=0.0)
