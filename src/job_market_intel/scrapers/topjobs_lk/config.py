"""Configuration for the TopJobs (topjobs.lk) scraper -- Sri Lanka.

Measured on the live site on 2026-11-20 rather than assumed:

  * **Discovery** is a server-rendered JSP table,
    ``/applicant/vacancybyfunctionalarea.jsp?jst=OPEN&pageNo=<n>`` (page 1
    takes no ``pageNo``). ``jst=OPEN`` is the whole open board, not one
    functional area, and it is the only filter applied.
  * **Paging is real and deep**: pages 1-6 held 873, 922, 944, 929, 890 and
    30 rows -- 4,583 unique job codes in total. Consecutive pages overlap by
    exactly one row (the page boundary repeats), so rows are de-duplicated on
    the job code (``jc``).
  * A listing row is **not** a link: the whole ``<tr>`` is clickable through
    ``onclick="createAlert('rid','ac','jc','ec','id')"``. The four codes in
    that call build the detail URL, so there is nothing to follow without
    parsing the attribute:
    ``/employer/JobAdvertismentServlet?rid=..&ac=..&jc=..&ec=..&pg=..``.
  * The listing carries what the detail page lacks -- **opening date, closing
    date and town** -- and the detail page carries what the listing lacks
    (an ``ad-status`` label set). Both are read.
  * **Most ads are image-only**: 71 of 75 sampled ads had an ``<img>`` and no
    body text. Image-only ads are still stored; they keep the title,
    employer, dates, town and detail URL, and say why the body is missing.
  * robots.txt (HTTP 200) allows the listing and detail paths; nothing this
    scraper requests is disallowed. No key, no registration, no proxy.

Running cost
------------
A listing page is ~2 MB of HTML and a detail page ~40-130 KB. All listing
pages are walked for the rotation below (the board is ~4.5k open ads and a
capped run must not re-read only the first page forever), then at most
``max_jobs_per_run`` detail pages are fetched at
``inter_request_delay_seconds`` apart.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TopJobsLkSettings(BaseSettings):
    """Configuration for the TopJobs board (Sri Lanka)."""

    model_config = SettingsConfigDict(env_prefix="TOPJOBS_LK_", extra="ignore")

    base_url: str = Field(default="https://topjobs.lk", description="Site root.")
    listing_path: str = Field(
        default="/applicant/vacancybyfunctionalarea.jsp",
        description="Server-rendered listing page.",
    )
    listing_query: str = Field(
        default="jst=OPEN",
        description="Query string: the whole open board, newest first.",
    )

    max_listing_pages: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Listing pages to walk. The board had 6 open pages on 2026-11-20.",
    )
    max_jobs_per_run: int = Field(
        default=250,
        ge=1,
        description="Cap on detail pages fetched and postings persisted in one run.",
    )

    #: The newest rows are always taken, so a run never misses what was just
    #: posted. The rest of the budget comes from a window that moves with the
    #: calendar (see ``start_offset``), so the older tail is covered over time
    #: instead of the same first N rows being re-read on every run.
    fresh_rows: int = Field(
        default=120,
        ge=0,
        description="Newest listing rows always sampled, ahead of the rotating window.",
    )
    #: ``None`` = derive the window start from today's date, advancing one
    #: budget-width per day. Pinning this makes a run reproducible (tests use
    #: it); CI leaves it unset.
    start_offset: int | None = Field(
        default=None,
        ge=0,
        description="Override for the rotating window start.",
    )

    fetch_details: bool = Field(
        default=True,
        description="Fetch each ad for its body text and ad-status labels. "
        "About 95% of ads are image-only, but the labels are only on the detail page.",
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)", description="Identifying UA."
    )
    request_timeout_seconds: int = Field(default=45, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=1.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=10.0, ge=0.0)

    #: Measured 2026-11-20: 75 detail pages were fetched at ~0.6-1.0 s each
    #: with no throttling response. 0.7 s keeps a 250-job run around 4-5
    #: minutes while staying polite to a small single-server board.
    inter_request_delay_seconds: float = Field(default=0.7, ge=0.0)

    stop_after_empty_pages: int = Field(
        default=1, ge=1, description="Consecutive empty listing pages that end discovery."
    )
