"""Configuration for the JobsNepal scraper (Nepal).

Measured on the live site on 2026-10-18 rather than assumed:

  * **Discovery** is ``/top-job`` with **path-based** pagination,
    ``/top-job?page=2`` -- which returned **8 new** postings. Hrefs are
    **relative**.
  * Detail pages carry **no schema.org JSON-LD**. Everything is in labelled
    rows::

        Job posted on 05 Oct, 2026 Apply before 18 Oct, 2026
        LOCATION Central Office
        Salary: Negotiable as per competence and experience.
        Position Type Full Time
        Experience 7+ years
        Category Accounting/Finance
        Posted Date 05 Oct, 2026

    with the body in the main container. Dates are **dd Mmm, yyyy** (Nepali
    convention).
  * ``Salary`` reads ``"Negotiable as per competence and experience."`` -- prose,
    not a figure, so no salary is stored.
  * ``og:title`` / ``og:description`` are **site-wide** and must not be used.
  * robots.txt: ``User-agent: *`` with an empty ``Disallow:`` -- the whole site
    is permitted.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobsNepalSettings(BaseSettings):
    """Configuration for the JobsNepal board (Nepal)."""

    model_config = SettingsConfigDict(env_prefix="JOBSNEPAL_", extra="ignore")

    base_url: str = Field(default="https://www.jobsnepal.com", description="Site root.")
    listing_path: str = Field(default="/top-job", description="Server-rendered listing page.")

    max_pages: int = Field(
        default=6, ge=1, le=200, description="Listing pages to walk. ~12 postings per page."
    )
    max_jobs_per_run: int = Field(
        default=60, ge=1, description="Cap on postings persisted in one run."
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)", description="Identifying UA."
    )
    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Detail pages are ~70 KB. 1.5s is comfortably inside what the site tolerates.
    inter_request_delay_seconds: float = Field(default=1.5, ge=0.0)

    fetch_description: bool = Field(
        default=True, description="Fetch each detail page for the body and metadata."
    )
    stop_after_repeated_empty_pages: int = Field(default=2, ge=1)
    min_links_per_page: int = Field(
        default=5, ge=1, description="Tail threshold. Pages carry ~12 postings."
    )
