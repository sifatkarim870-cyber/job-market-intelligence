"""Configuration for the Emploi Bénin (emploibenin.com) scraper.

Measured on the live site on 2026-11-20 rather than assumed:

  * **Discovery** is a server-rendered search directory at
    ``/recherche-jobs-benin``; page 1 takes no query string and page N takes
    ``?page=N``. The pager renders as ``Page : 1 2 3 ... 9``.
  * **The board is 209 offers over 9 pages** (eight pages of 25 ad links and a
    final page of 9). Pages do not overlap. A page past the last one returns
    HTTP 200 with zero ad links, which is the natural stop signal.
  * Ad URLs look like ``/offre-emploi-benin/<slug>``. Most slugs end in the
    numeric ad id, but not all, so the URL is only the discovery key -- the
    canonical id is JSON-LD ``identifier.value`` on the detail page.
  * Each detail page embeds a Schema.org ``JobPosting`` block with title,
    datePosted, validThrough, employmentType, hiringOrganization,
    jobLocation and an HTML description. Some ads have the same
    unescaped-quote defect inside ``description`` that Emploi.ci and Emploi.cd
    have; it is repaired before parsing.
  * ``jobLocation.address.addressCountry`` is the plain label ``Benin`` here
    (not the boilerplate country the DRC sister site writes), and
    ``addressRegion`` is a list of cities rather than a region.
  * robots.txt (HTTP 200) allows ``/`` and asks for ``Crawl-delay: 10``. That
    delay is honoured for every request, so a full board takes ~40 minutes and
    a capped run is the normal mode.
  * No key, no registration, no proxy.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmploiBeninSettings(BaseSettings):
    """Runtime configuration for the Emploi Bénin scraper."""

    model_config = SettingsConfigDict(
        env_prefix="EMPLOIBENIN_COM_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(default="https://www.emploibenin.com", description="Site root.")
    search_url: str = Field(
        default="https://www.emploibenin.com/recherche-jobs-benin",
        description="Server-rendered search directory; page 1 takes no query string.",
    )

    max_pages: int = Field(
        default=12,
        ge=1,
        le=50,
        description="Search pages to walk. The board had 9 pages on 2026-11-20.",
    )
    max_jobs_per_run: int = Field(
        default=120,
        ge=1,
        description="Cap on detail pages fetched and postings persisted in one run.",
    )

    #: The newest rows are always taken, so a run never misses what was just
    #: posted. The rest of the budget comes from a window that moves with the
    #: calendar (see ``start_offset``), so the older tail is covered over time
    #: instead of the same first page being re-read forever.
    fresh_rows: int = Field(
        default=40,
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
