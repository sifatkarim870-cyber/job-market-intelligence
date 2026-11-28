"""Configuration for the UWV Werk.nl (werk.nl) scraper -- Netherlands.

Werk.nl is the Dutch public employment service (UWV) job board, and it needs
no key, no registration and no proxy. It is not a plain-HTML board: the
vacancy search is a small Spring Boot JSON API behind the Angular app at
``/nl/vacatures``, so this is a bespoke client rather than the generic
``html_scraper``.

**robots.txt** (``https://www.werk.nl/robots.txt``, HTTP 200, 85 bytes)::

    User-agent: *

    Disallow: /webpublicaties

    Sitemap: https://www.werk.nl/nl/sitemap.xml

The default ``*`` group disallows only ``/webpublicaties`` (a publications
section this scraper never touches); everything the scraper reads -- the
``/werkzoekenden/...`` API and the ``/nl/vacatures`` page -- is allowed, and
no ``Crawl-delay`` is advertised. A polite sub-second gap between requests is
kept anyway.

**The API.** The Angular app reads its endpoint base from
``.../zoekenvacatures/api/configuration`` and then talks to three routes:

* ``POST .../api/search`` -- the listing. The body is
  ``{"keywords": "", "location": "", "currentPage": N}`` (``N`` is **1-based**;
  ``0`` is a 500). Empty keywords/location return the whole board,
  newest-first, 20 items per page; ``totalResults`` was 281,590 on
  2026-11-28. The response carries the items plus a very large ``facets``
  block (the ``JOB_CATEGORY`` facet alone lists 6,070 values).
* ``GET .../api/vacature/{referenceNumber}`` -- one vacancy's full detail
  (title, proposition.function.description, employer, salary indication,
  contract, work hours, application methods).
* ``GET .../api/configuration`` -- also the CSRF bootstrap: it sets the
  ``XSRF-TOKEN`` cookie, whose value must be echoed in the ``X-XSRF-TOKEN``
  header that every ``POST /search`` requires. Without it the search answers
  HTTP 400 (the framework's CSRF filter); with a wrong payload shape it
  answers HTTP 500.

**Freshness / coverage.** The listing is newest-first. The newest
``fresh_pages`` pages are always read so a run never misses what was just
posted; the rest of the page budget comes from a window that advances by the
calendar day over the whole result set, so older vacancies are covered over
successive runs instead of the same first page being re-read forever.
``start_page`` pins that window for a reproducible run.

**Scope.** One row is one vacancy. The list response supplies the title,
employer, city, hours and contract type; the detail response supplies the
description, the salary indication and the employer's own application URL.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_API = "https://www.werk.nl/werkzoekenden/mijn-werkmap/kia/publiek/zoekenvacatures/api"


class WerkNlSettings(BaseSettings):
    """Runtime configuration for the UWV Werk.nl (werk.nl) scraper."""

    model_config = SettingsConfigDict(
        env_prefix="WERK_NL_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(default="https://www.werk.nl", description="Site root.")
    configuration_url: str = Field(
        default=f"{_API}/configuration",
        description="Endpoint map + CSRF (XSRF-TOKEN) bootstrap.",
    )
    search_url: str = Field(default=f"{_API}/search", description="Vacancy search (POST).")
    detail_url_template: str = Field(
        default=f"{_API}/vacature/{{job_id}}",
        description="Per-vacancy detail (GET), keyed by numeric referenceNumber.",
    )
    public_job_url_template: str = Field(
        default="https://www.werk.nl/nl/vacatures/{job_id}",
        description="Human-facing ad URL used for original_url.",
    )
    max_jobs_per_run: int = Field(
        default=300,
        ge=1,
        description="Cap on detail pages fetched and postings persisted in one run.",
    )
    page_size: int = Field(
        default=20,
        ge=1,
        description="Items per search page; the API fixes this at 20.",
    )
    #: The newest pages are always read, so a run never misses what was just
    #: posted. The rest of the budget comes from a window that moves with the
    #: calendar (see ``start_page``).
    fresh_pages: int = Field(
        default=3,
        ge=0,
        description="Newest search pages always read, ahead of the rotating window.",
    )
    #: ``None`` = derive the window start page from today's date, advancing one
    #: budget-width per day. Pinning this makes a run reproducible (tests use
    #: it); CI leaves it unset.
    start_page: int | None = Field(
        default=None,
        ge=1,
        description="Override for the rotating window start page.",
    )
    max_pages_scanned: int = Field(
        default=400,
        ge=1,
        description="Hard ceiling on the rotating window size (board is ~14k pages).",
    )
    fetch_details: bool = Field(
        default=True,
        description="Fetch each vacancy's detail for its description and salary. A run "
        "is far less useful without it, but the switch keeps offline tests honest.",
    )

    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        description="Browser user agent; the board's robots.txt bans no token.",
    )
    request_timeout_seconds: float = Field(default=45.0, gt=0)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: No Crawl-delay is advertised. Half a second keeps a 300-detail run under
    #: four minutes while staying polite to a public employment service.
    inter_request_delay_seconds: float = Field(default=0.5, ge=0.0)
