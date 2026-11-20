"""Configuration for the Rwandajob.com (rwandajob.com) scraper.

Measured on the live site on 2026-11-20 rather than assumed:

  * **Discovery** is the server-rendered search directory
    ``/job-vacancies-search-rwanda``; page 1 carries no query string and page N
    takes ``?page=N``. The pager renders as ``Page : 1 2 3 4 5``.
  * **The board held 116 offers over 5 pages** (four pages of 25 ad links and a
    final page of 16). Pages do not overlap. A page past the last one returns
    HTTP 200 with zero ad links, which is the natural stop signal.
  * Ad URLs are ``/job-vacancies-rwanda/<slug>-<id>``. Sampled slugs end in the
    numeric ad id, but the URL is still only the discovery key -- the canonical
    id is JSON-LD ``identifier.value`` on the detail page.
  * Each detail page embeds a Schema.org ``JobPosting`` block with title,
    datePosted, validThrough, employmentType, hiringOrganization (with a logo),
    jobLocation and an HTML description. The board's ``datePosted`` tracks the
    ad: the oldest page-5 ads carry ``2026-09-29`` while the newest page-1 ads
    carry ``2026-11-20``, and the visible ``Published on`` line agrees, so it is
    read as the real posting date.
  * The same unescaped-quote JSON-LD defect the AfricaWork sister boards have
    was measured here too (3 of a 9-ad sample needed the description field
    dropped), so the block is repaired before parsing and the body is taken from
    ``div.job-description``.
  * ``jobLocation.address.addressCountry`` is the clean label ``Rwanda``.
    ``addressRegion`` is NOT a region: it is the ``-``-joined list of provinces
    the ad is open to (``"Eastern Province - Kigali Province - ... -
    International"``), so it is used for remote detection only and never stored
    as a place.
  * ``baseSalary`` was absent on every sampled ad, so no amount is invented;
    rows carry currency RWF and period monthly as a statement about the market.
  * robots.txt (HTTP 200) allows the search and ad paths and asks for
    ``Crawl-delay: 10``, honoured between any two requests, so a full board
    costs ~20 minutes and a capped 120-row window is the normal mode.
  * No key, no registration, no proxy.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RwandaJobSettings(BaseSettings):
    """Runtime configuration for the Rwandajob.com scraper."""

    model_config = SettingsConfigDict(
        env_prefix="RWANDAJOB_COM_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(default="https://www.rwandajob.com", description="Site root.")
    search_url: str = Field(
        default="https://www.rwandajob.com/job-vacancies-search-rwanda",
        description="Server-rendered search directory; page 1 takes no query string.",
    )

    max_pages: int = Field(
        default=8,
        ge=1,
        le=50,
        description="Search pages to walk. The board had 5 pages on 2026-11-20.",
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
