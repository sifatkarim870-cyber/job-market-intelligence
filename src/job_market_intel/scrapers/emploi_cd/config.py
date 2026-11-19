"""Configuration for the Emploi.cd (DR Congo) scraper.

Measured on the live site on 2026-11-20 rather than assumed:

  * **Discovery** is a server-rendered search directory at
    ``/recherche-jobs-congo-rdc``; page 1 takes no query string and page N
    takes ``?page=N`` (``?page=0`` is byte-identical to page 1).
  * **The board is small and fully pageable**: 90 offers over 4 pages
    (24, 25, 25 and 15 links), 89 unique ad URLs. Pages do not overlap.
    A page after the last one returns HTTP 200 with zero ad links, which is
    the natural stop signal.
  * Ad URLs look like
    ``/offre-emploi-rdc-republique-democratique-congo/<slug>``. Some slugs
    end in the numeric ad id (``-505848``) and some do not
    (``business-development-lead-beni-butembo-goma-bunia``), so the URL is
    not a reliable identifier on its own. Every detail page carries the
    canonical id in JSON-LD ``identifier.value``.
  * Each detail page embeds a Schema.org ``JobPosting`` block with title,
    datePosted, validThrough, employmentType, hiringOrganization,
    jobLocation and an HTML description. One sampled ad had the same
    unescaped-quote defect inside ``description`` that Emploi.ci has; it is
    repaired before parsing.
  * robots.txt (HTTP 200) allows the search and ad paths and asks for
    ``Crawl-delay: 10``. That delay is honoured for every request, so run
    sizing is measured in minutes, not seconds.
  * No key, no registration, no proxy.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmploiCdSettings(BaseSettings):
    """Runtime configuration for the Emploi.cd scraper."""

    model_config = SettingsConfigDict(
        env_prefix="EMPLOI_CD_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(default="https://www.emploi.cd", description="Site root.")
    search_url: str = Field(
        default="https://www.emploi.cd/recherche-jobs-congo-rdc",
        description="Server-rendered search directory; page 1 takes no query string.",
    )

    max_pages: int = Field(
        default=8,
        ge=1,
        le=50,
        description="Search pages to walk. The board had 4 pages on 2026-11-20.",
    )
    max_jobs_per_run: int = Field(
        default=90,
        ge=1,
        description="Cap on detail pages fetched and postings persisted in one run.",
    )

    #: The newest rows are always taken, so a run never misses what was just
    #: posted. If the board grows past ``max_jobs_per_run``, the rest of the
    #: budget comes from a window that moves with the calendar (see
    #: ``start_offset``), so the older tail is covered over time instead of the
    #: same first page being re-read forever.
    fresh_rows: int = Field(
        default=30,
        ge=0,
        description="Newest listing rows always sampled, ahead of the rotating window.",
    )
    #: ``None`` = derive the window start from today's date, advancing one
    #: budget-width per day. Pinning this makes a run reproducible (tests and
    #: manual runs use it); CI leaves it unset.
    start_offset: int | None = Field(
        default=None,
        ge=0,
        description="Override for the rotating window start.",
    )

    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        description="Browser user agent; the site serves plain HTML to it.",
    )
    request_timeout: float = Field(default=30.0, gt=0)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=5.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=30.0, ge=0.0)

    #: robots.txt asks for Crawl-delay: 10. This is the delay between any two
    #: requests (listing page or ad page), not a per-page sleep on top.
    rate_limit_delay: float = Field(default=10.0, ge=0.0)

    stop_after_empty_pages: int = Field(
        default=1,
        ge=1,
        description="Consecutive ad-link-free listing pages that end discovery.",
    )
