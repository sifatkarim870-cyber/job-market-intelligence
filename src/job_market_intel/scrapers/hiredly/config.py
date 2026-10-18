"""Configuration for the Hiredly scraper (Malaysia).

Measured on the live site on 2026-10-18 rather than assumed:

  * **The host is ``my.hiredly.com``, not ``hiredly.com``.** Requesting
    ``https://hiredly.com/jobs/<slug>`` 302s to
    ``my.hiredly.com/?utm_medium=shortened_link&...&redirect_nonexistent_short_links``
    -- the homepage, with no posting on it. The listing at
    ``hiredly.com/jobs`` redirects the other way, to
    ``my.hiredly.com/jobs?signup=false``. Both hosts serve the site; only the
    ``my.`` one serves detail pages.
  * **Listing**: ``/jobs?page=N`` returns **30 distinct postings per page**,
    verified with zero overlap between pages 1, 2, 3, 5, 10 and 20 (180
    cumulative). There is no "load more" control and no visible pager; the
    page number is the only cursor.
  * **Posting links** are ``/jobs/jobs-malaysia-<company>-job-<title>-<slug>``.
    The slug is long and self-describing, and the trailing ``-<id>`` varies,
    so the whole slug is the natural key.
  * **Rate limiting is real.** After roughly 60-80 detail requests inside a few
    minutes the site stops serving ``#__NEXT_DATA__`` at all -- the page still
    returns HTTP 200 and still has a title, but the JSON blob is gone. A burst
    of 30 with no delay returned nothing usable. So the delay is not politeness,
    it is the difference between a working run and an empty one.
  * **The record is ``#__NEXT_DATA__ -> props.pageProps.job``.** There is also
    a schema.org ``ld+json`` block and it is NOT interchangeable: for the same
    posting the two disagreed on the address (``55, Jalan SS 1/23`` / 47300 vs
    ``21, Jalan SS 22a/2`` / 47400). ``ld+json`` is generated from the
    employer's own profile; ``__NEXT_DATA__`` is the posting. Use the latter.
  * ``props.pageProps.similarJobs`` is a list of **other** postings on the same
    page, each with its own title, company and salary.
  * ``salary`` is a display string: ``"4000 - 6000"``, or ``"Undisclosed"``.
    The authoritative figures are in
    ``structuredJobData.baseSalary.value.minValue/maxValue`` with
    ``unitText: "MONTH"`` and ``currency: "MYR"``.
  * robots.txt: ``User-agent: *`` / ``Allow: /``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HiredlySettings(BaseSettings):
    """Configuration for the Hiredly board (Malaysia)."""

    model_config = SettingsConfigDict(env_prefix="HIREDLY_", extra="ignore")

    #: ``my.`` is load-bearing; see the module docstring.
    base_url: str = Field(default="https://my.hiredly.com", description="Site root.")
    listing_path: str = Field(default="/jobs", description="JS-rendered listing.")

    max_pages: int = Field(
        default=3, ge=1, le=100, description="Listing pages to walk, 30 postings each."
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
        default=5.0, ge=0.0, description="Settle time after domcontentloaded before reading."
    )
    #: Wait for the JSON blob rather than for a clock. Without it the run is at
    #: the mercy of when Next.js finishes hydrating.
    data_wait_seconds: int = Field(default=25, ge=1)
    detail_render_attempts: int = Field(
        default=3, ge=1, le=6, description="Tries per detail page, with a growing pause."
    )

    #: Measured: a burst of 30 with no delay returned 30 unusable pages. 5s is
    #: the conservative end of what tested clean; see the module docstring.
    inter_request_delay_seconds: float = Field(default=5.0, ge=0.0)
    #: Extra pause before a retry, on top of the per-page delay. The site
    #: recovers, but not instantly.
    retry_backoff_seconds: float = Field(default=15.0, ge=0.0)
