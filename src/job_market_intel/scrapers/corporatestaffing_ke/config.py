"""Configuration for the Corporate Staffing Services (Kenya) scraper.

Measured on the live site on 2026-10-18 rather than assumed:

  * **Discovery** is ``/jobs/`` with **path-based** pagination,
    ``/jobs/page/2/`` -- which returned **40 new** postings. The hrefs are
    **absolute** (measured 40 absolute, 0 relative).
  * ``robots.txt`` is ``User-agent: *`` with an empty ``Disallow:`` -- the whole
    site is permitted, so there is no query-string trap.
  * Detail pages carry **no schema.org JSON-LD**. Everything is in labelled rows::

        Date Posted: 16/10/2026
        Job Type: Full Time
        Employer: APA Life Assurance Company Ltd
        Salary: Open
        Location: Nairobi
        Deadline: 26/10/2026

    with the body in ``main``. Dates are **dd/mm/yyyy** (Kenyan convention), not
    ISO and not mm/dd/yyyy -- a parser that assumes ISO would return nothing for
    every posting.
  * ``Salary: Open`` / ``Salary: Confidential`` is prose, not a figure, so no
    salary is stored.
  * ``og:title`` IS the job title here (contrast Fiji Sun, where it is the
    site's name). It is still not used: ``<h1>`` is the same string and is
    closer to the data.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CorporateStaffingSettings(BaseSettings):
    """Configuration for the Corporate Staffing Services (Kenya) board."""

    model_config = SettingsConfigDict(env_prefix="CORPORATE_STAFFING_", extra="ignore")

    base_url: str = Field(default="https://www.corporatestaffing.co.ke", description="Site root.")
    listing_path: str = Field(default="/jobs/", description="Server-rendered listing page.")
    page_path_template: str = Field(
        default="/jobs/page/{page}/", description="Path-based pagination."
    )

    max_pages: int = Field(
        default=6, ge=1, le=200, description="Listing pages to walk. ~40 postings per page."
    )
    max_jobs_per_run: int = Field(
        default=120, ge=1, description="Cap on postings persisted in one run."
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)", description="Identifying UA."
    )
    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Detail pages are ~310 KB -- the largest in this batch. 1.5s is
    #: comfortably inside what the site tolerates; no throttle was observed.
    inter_request_delay_seconds: float = Field(default=1.5, ge=0.0)

    fetch_description: bool = Field(
        default=True, description="Fetch each detail page for the body and metadata."
    )
    stop_after_repeated_empty_pages: int = Field(default=2, ge=1)
    min_links_per_page: int = Field(
        default=5, ge=1, description="Tail threshold. Pages carry ~40 postings."
    )
