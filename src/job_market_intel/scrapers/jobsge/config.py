"""Configuration for the Jobs.ge scraper (Georgia).

Measured on the live site on 2026-10-18 rather than assumed:

  * **Two language paths, and only one of them has the description.**
    ``/en/jobs`` and ``/en/?view=jobs&id=N`` render the ad's *title* and
    employer in English and then stop:

        Entrée is pleased to announce an opening for the position of
        Restaurant Supervisor.

        See full text of this announcement in Georgian.

    That is the whole ``/en/`` body, 548 characters. The Georgian page at
    ``/ge/?view=jobs&id=N`` carries the full text -- 4,421 characters for the
    same posting. So the listing is read from ``/en/`` (English titles come
    free with it) and the description from ``/ge/``. Two different hosts paths
    on one site, and picking either consistently gives a worse corpus.

  * **The listing is a plain HTML ``<table>``, not a card list.** Header row:
    ``* | VIP Advertisements | | Provided By | Published | Deadline``. Each
    posting is a ``<tr>`` whose first cell holds
    ``<a href="/{lang}/?view=jobs&id=761321">``.

  * **Posting ids are numeric query parameters**, not slugs:
    ``/en/?view=jobs&id=761321``. That is the natural key.

  * **Dates are Georgian month names with no year**, on one line:
    ``გამოქვეყნდა: 16 ოქტომბერი / ბოლო ვადა: 16 ნოემბერი``
    ("Published: 16 October / Deadline: 16 November").

  * **No salary field.** Pay appears only in prose inside the ad body
    ("საწყისი ანაზღაურება: 1500 ლარი" = "starting salary: 1500 lari"), mixed
    with internship and trainee rates in the same ad. Scraping a number out of
    prose is the "looks like a value but isn't" trap; it is left unrecorded.

  * **No location field.** Tbilisi appears inside the body text, never
    structured. Country-only, honestly, rather than regexing a city out of
    prose.

  * **Pagination is ``?page=N``** and returns 308 postings on page 1; page 2
    yielded 300 further ids with no overlap.

  * Not Cloudflare-walled -- it was one of only four boards in the "JS-rendered,
    no anti-bot" group that turned out to be genuinely buildable.

  * robots.txt: ``User-agent: *`` / ``Allow: /``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobsGeSettings(BaseSettings):
    """Configuration for the Jobs.ge board (Georgia)."""

    model_config = SettingsConfigDict(env_prefix="JOBSGE_", extra="ignore")

    base_url: str = Field(default="https://jobs.ge", description="Site root.")

    #: The listing is read from the English path -- the titles are English and
    #: it costs nothing extra -- while the description comes from the Georgian
    #: path, which is the only one that has one.
    listing_path: str = Field(default="/en/jobs", description="Listing, English titles.")
    listing_lang: str = Field(default="en")
    detail_lang: str = Field(default="ge", description="Georgian: the only full text.")

    max_pages: int = Field(default=2, ge=1, le=100, description="Listing pages to walk.")
    max_jobs_per_run: int = Field(
        default=60, ge=1, description="Cap on postings persisted in one run."
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)", description="Identifying UA."
    )

    headless: bool = Field(default=True, description="Run the browser headless.")
    page_load_timeout_seconds: int = Field(default=60, ge=1)
    render_wait_seconds: float = Field(default=2.0, ge=0.0)
    #: The listing is server-rendered HTML, so there is nothing to wait for
    #: beyond the browser finishing the document. Kept explicit rather than
    #: omitted, because "why is this one different" is the question this
    #: project keeps paying for.
    settle_wait_seconds: float = Field(default=1.0, ge=0.0)
    detail_render_attempts: int = Field(default=3, ge=1, le=6)
    inter_request_delay_seconds: float = Field(default=2.0, ge=0.0)
    retry_backoff_seconds: float = Field(default=10.0, ge=0.0)
