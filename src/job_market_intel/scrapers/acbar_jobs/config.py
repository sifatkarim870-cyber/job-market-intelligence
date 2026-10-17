"""Configuration for the ACBAR jobs scraper (Afghanistan).

Measured on the live site on 2026-10-18 rather than assumed:

  * **Discovery** is ``/en/jobs?page=N``. Exactly **20** posting links, and the
    pager is real: ``?page=2`` returned **20 new** paths. ``/en/site-page/2`` is
    HTTP 404 -- that is the *pagination chrome* path, not the pager.

  * Hrefs are **absolute** (measured 20 absolute, 0 relative). The pattern makes
    the host prefix optional; Angola Emprego was the same way and a relative-only
    pattern there matched nothing at all on a board serving 15 postings a page.

  * Detail pages carry **no schema.org JSON-LD and no ``og:`` meta tags**, so
    this is markup extraction. Everything is in a ``<dl class=
    "acbar-jd__info-table">`` of label/value rows:

        <div class="acbar-jd__info-row">
          <dt class="acbar-jd__info-term">Published</dt>
          <dd class="acbar-jd__info-desc">2026-10-14</dd>
        </div>

    Measured keys: ``Type``, ``Location``, ``Category``, ``Published``,
    ``Nationality``, ``Gender``, ``Salary``, ``Contract Duration``,
    ``Vacancy Number``, ``No of Job``, plus ``Education`` and ``Experience`` in a
    slightly different label/value pair shape. The closing date is separate, in
    ``.acbar-jd__deadline-label`` / ``.acbar-jd__deadline-value``.

The two traps
-------------
1. **The body container contains a related-jobs carousel.** ``.acbar-jd__body``
   is 4680 characters and holds **six** ISO dates -- all of them belonging to
   *other* postings, in a ``.acbar-jd__related`` block with a
   ``.acbar-jd__deadline-banner``-style carousel. A naive "first ISO date in the
   body" extraction assigns a deadline from an unrelated job. Measured: the ten
   dates found were byte-identical across two different postings, which is what
   gave it away. The related block is removed before the body text is taken,
   after which **zero** dates remain.

2. **``Salary`` is prose, not a number.** Measured values are ``"As Per
   Organization"``, ``"As per scale"`` and ``"Negotiable"``. Nothing is stored --
   the same treatment CareerJunction's ``"R Undisclosed"`` and Jobweb Ghana's
   site-wide placeholder get.

robots.txt is 24 bytes: ``User-agent: *`` with an empty ``Disallow:``, i.e. the
whole site is permitted.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AcbarJobsSettings(BaseSettings):
    """Configuration for the ACBAR jobs board (Afghanistan)."""

    model_config = SettingsConfigDict(env_prefix="ACBAR_JOBS_", extra="ignore")

    base_url: str = Field(default="https://www.acbar.org", description="Site root.")
    listing_path: str = Field(default="/en/jobs", description="Server-rendered listing page.")

    max_pages: int = Field(
        default=6,
        ge=1,
        le=200,
        description="Listing pages to walk. 20 postings per page, measured to paginate.",
    )

    max_jobs_per_run: int = Field(
        default=100,
        ge=1,
        description="Cap on postings persisted in one run (ACBAR_JOBS_MAX_JOBS_PER_RUN).",
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA. No key or registration is involved.",
    )

    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Detail pages are ~96 KB. 1.5s is comfortably inside what the site
    #: tolerates; no throttle was observed.
    inter_request_delay_seconds: float = Field(default=1.5, ge=0.0)

    fetch_description: bool = Field(
        default=True,
        description=(
            "Fetch each detail page for the info table and body. Listing pages "
            "carry only a path, so without this there is nothing to store."
        ),
    )

    stop_after_repeated_empty_pages: int = Field(default=2, ge=1)
    min_links_per_page: int = Field(
        default=5,
        ge=1,
        description="Tail threshold. Pages carry 20 postings.",
    )
