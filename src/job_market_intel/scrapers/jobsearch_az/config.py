"""Configuration for the JobSearch.az scraper (Azerbaijan).

Measured on the live site on 2026-10-18 rather than assumed:

  * **Discovery** is ``/vacancies``, rendered with a headless browser. The site
    is a Nuxt SPA; plain HTTP returns 512 KB of bundle with zero anchors. After
    the page renders it is a plain ``div.list__item`` card list -- **30** of
    them -- each linking ``/vacancies/<slug>``.
  * A **"Daha ətraflı"** ("Load more") control appends more cards. Playwright's
    own click times out on it because a sticky scroller intercepts the pointer
    event, so the client clicks with ``force=True``.
  * Hrefs are **relative**.
  * Detail pages carry precise hooks: ``h1.vacancy__title`` (job),
    ``h1.company__title`` (employer), ``.vacancy__deadline``
    ("Son tarix 17 noy 2026"), and ``#content_block`` for the description.
  * The **posting date is only on the card**, year-less: "Bu gün", "Dünən",
    "16 okt".
  * There is **no salary** (the card's ``li.money`` renders empty), no JSON-LD
    and no ``og:`` meta tags.
  * robots.txt: ``User-agent: *`` / ``Allow: /`` -- the whole site is permitted.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobSearchAzSettings(BaseSettings):
    """Configuration for the JobSearch.az board (Azerbaijan)."""

    model_config = SettingsConfigDict(env_prefix="JOBSEARCH_AZ_", extra="ignore")

    base_url: str = Field(default="https://jobsearch.az", description="Site root.")
    listing_path: str = Field(default="/vacancies", description="JS-rendered listing page.")

    max_pages: int = Field(
        default=1,
        ge=1,
        le=50,
        description="Listing passes. The board paginates by 'Load more', not by URL, "
        "so more than one pass only re-reads the same list.",
    )
    max_jobs_per_run: int = Field(
        default=60, ge=1, description="Cap on postings persisted in one run."
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)", description="Identifying UA."
    )

    headless: bool = Field(default=True, description="Run the browser headless.")
    page_load_timeout_seconds: int = Field(default=60, ge=1)
    render_wait_seconds: float = Field(
        default=1.5,
        ge=0.0,
        description="Seconds to wait after networkidle before reading the listing.",
    )
    #: ``networkidle`` fires before ``#content_block`` arrives on roughly one
    #: posting in eight, so the description node is waited for by selector
    #: rather than by a fixed pause. See ``_render_one``.
    description_wait_seconds: int = Field(default=20, ge=1)
    detail_render_attempts: int = Field(
        default=2, ge=1, le=5, description="Tries per detail page before recording a failure."
    )
    #: Clicking "Daha ətraflı" this many times. The measured 30 cards arrived
    #: within the first two, but the cap is generous because the board grows.
    max_load_more_clicks: int = Field(default=6, ge=0, le=30)

    #: A rendered detail page is ~700 KB. 2s between fetches keeps this polite.
    inter_request_delay_seconds: float = Field(default=2.0, ge=0.0)

    fetch_description: bool = Field(
        default=True, description="Render each detail page for its description."
    )
