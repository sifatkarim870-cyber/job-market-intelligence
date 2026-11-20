"""Configuration for the Revolico (Cuba) jobs scraper.

Measured on the live site on 2026-11-21 rather than assumed:

  * **Discovery** is the server-rendered Next.js search page. The employers'
    board is the subcategory
    ``/search?category=empleos_&subcategory=empleos-ofertas-de-empleo``
    ("Ofertas de Empleo"); the sibling ``empleos-busco-empleo`` holds
    job-seekers and is deliberately not walked.
  * Pagination is ``?page={n}`` and each page carries ~100 ads; the employers'
    board held hundreds of pages when measured.
  * Ad URLs are ``/item/<slug>-<id>`` and ``<id>`` is the stable id.
  * Every page embeds its data in ``<script id="__NEXT_DATA__">``; the ads are
    the ``AdType:*`` entries of ``props.pageProps.__APOLLO_STATE__``. Listings
    carry partial ads (no body), so one detail request is made per ad.
  * There is no original posting date and no employer field; ``price`` is often
    a placeholder, so it is never treated as a disclosed salary.
  * ``robots.txt`` is a generic ``*`` group that allows everything except
    ``/checkout/``, ``/cdn-cgi/``, ``/account``, ``/auth``, ``/favorites/``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RevolicoCuSettings(BaseSettings):
    """Configuration for Revolico (Cuba) jobs."""

    model_config = SettingsConfigDict(env_prefix="REVOLICO_CU_", extra="ignore")

    base_url: str = Field(default="https://www.revolico.com", description="Site root.")
    search_path: str = Field(default="/search", description="Server-rendered search page.")

    #: The parent jobs category. The search endpoint needs it alongside the
    #: subcategory: the subcategory slug alone returns an empty page.
    category: str = Field(default="empleos_", description="Empleos parent category slug.")
    subcategory: str = Field(
        default="empleos-ofertas-de-empleo",
        description="'Ofertas de Empleo' (employers). Never the job-seeker sibling.",
    )

    max_pages: int = Field(
        default=6,
        ge=1,
        le=200,
        description="Listing pages to walk. Each page carries ~100 ads.",
    )
    max_jobs_per_run: int = Field(
        default=200, ge=1, description="Cap on postings persisted in one run."
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)", description="Identifying UA."
    )
    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Search pages are ~400 KB and item pages ~65 KB. 0.5s keeps a full
    #: 200-ad run a few minutes while staying polite.
    inter_request_delay_seconds: float = Field(default=0.5, ge=0.0)

    fetch_detail: bool = Field(
        default=True, description="Fetch each item page for the body and metadata."
    )
    stop_after_repeated_empty_pages: int = Field(default=2, ge=1)
    min_ads_per_page: int = Field(
        default=20, ge=1, description="Tail threshold. Pages carry ~100 ads."
    )
