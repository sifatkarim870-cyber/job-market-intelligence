"""Configuration for the Robota.ua (robota.ua, Ukraine) scraper.

Measured on the live site on 2026-11-28 rather than assumed:

  * **The public website is behind Cloudflare.** ``robota.ua`` answers plain
    ``requests`` (and ``robots.txt`` itself) with HTTP 403 "Just a moment..."
    under a ``server: cloudflare`` header. ``curl_cffi`` impersonating a real
    Chrome TLS/HTTP2 fingerprint clears it and gets HTTP 200, so this source
    runs through ``curl_cffi`` like the other Cloudflare-fronted scraper
    packages. TLS verification stays on (no ``verify=False`` anywhere), no
    key, no login, no proxy.
  * **Discovery and detail are one GraphQL query.** The site is an Angular
    SPA whose bundle points at ``https://dracula.robota.ua/graphql`` (the
    ``graphqlApi`` environment value). The ``publishedVacancies`` query is
    unauthenticated and returns the whole public search -- title, full HTML
    description, salary, company, city/region, schedules, employment and work
    types -- paginated with ``pagination: {page, count}`` and sortable with
    ``sort: BY_DATE``. No separate detail request is needed.
  * **The API host's own robots.txt is permissive for the API.**
    ``https://dracula.robota.ua/robots.txt`` (HTTP 200) is a generic
    ``User-agent: *`` group that only disallows ``/swagger`` and ``/ui`` /
    ``/playground``; ``/graphql`` is allowed. The website's robots.txt
    (read through the cleared browser) only disallows ``/data/content/``,
    ``/cvphotos/``, ``/banner.aspx`` and ``/Export/*``.
  * **The board is large and live.** ``publishedVacancies.totalCount`` was
    **97,981** on 2026-11-28, newest-first by ``sortDate``, with no overlap
    between pages and 100 items per page accepted. Twelve rapid queries were
    answered with no rate limiting, but a modest pause between pages is kept
    anyway.
  * **Every posting is Ukraine-facing.** ``city.name`` is an English city
    label ("Kyiv") and ``city.region.name`` an oblast ("Kyiv oblast");
    ``salary.currency`` is the ISO code ``UAH``; ``workTypes`` are
    ``REMOTE``/``HYBRID``/``OFFICE``. The home market is therefore Ukraine
    (UA) and the home currency the hryvnia (UAH), both already seeded.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RobotaUaSettings(BaseSettings):
    """Runtime configuration for the Robota.ua scraper."""

    model_config = SettingsConfigDict(
        env_prefix="ROBOTA_UA_",
        case_sensitive=False,
        extra="ignore",
    )

    graphql_url: str = Field(
        default="https://dracula.robota.ua/graphql",
        description="Unauthenticated public GraphQL endpoint used for discovery and detail.",
    )
    web_base_url: str = Field(
        default="https://robota.ua",
        description="Public site base; a job's canonical URL is /vacancy/{id}.",
    )

    page_size: int = Field(
        default=100,
        ge=1,
        le=100,
        description="Rows per GraphQL page; 100 was accepted live on 2026-11-28.",
    )
    max_pages: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Hard cap on pages walked (20 x 100 = 2,000 candidates per run).",
    )
    max_jobs_per_run: int = Field(
        default=200,
        ge=1,
        description="Cap on unseen postings fetched and persisted in one run.",
    )

    impersonate: str = Field(
        default="chrome",
        description="curl_cffi browser TLS/HTTP2 profile; plain requests get Cloudflare 403.",
    )
    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        description="Browser user agent sent alongside the impersonated TLS profile.",
    )
    request_timeout_seconds: float = Field(default=45.0, gt=0)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=30.0, ge=0.0)

    #: Pause between GraphQL page requests. Twelve rapid queries were served
    #: without a 429, so this is politeness rather than a hard requirement.
    fetch_delay_seconds: float = Field(default=0.5, ge=0.0)
