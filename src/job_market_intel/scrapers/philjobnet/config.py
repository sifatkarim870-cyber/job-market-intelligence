"""Configuration for the PhilJobNet scraper (Philippines).

Measured on the live site on 2026-10-18 rather than assumed:

  * **Discovery** is ``/job-vacancies/`` with **no working pager**:
    ``?page=2`` returns 0 new postings, so all 10 postings sit on one page.
  * Hrefs are **relative** (measured 10 relative, 0 absolute).
  * Detail pages carry **no schema.org JSON-LD**. Everything is in a
    ``.portfolio-details`` block::

        BUILDING ADMINISTRATOR
        Salary not specified
        1PRIME RETAIL CORPORATION
        Apply now
        DUMAGUETE CITY (CAPITAL), NEGROS ORIENTAL
        COLLEGE GRADUATE
        Permanent
        Job Description
        Posted on 17 October 2026
        <description>

    or, when a salary is stated::

        BUSINESS DEVELOPMENT OFFICER
        ₱20,000.00
        I PROCESS LIAISON AND CONSULTANCY OPC
        Apply now
        BACUNGAN (LEON T. POSTIGO), ZAMBOANGA DEL NORTE
        ELEMENTARY GRADUATE
        Project-based
        Job Description
        Posted on 17 October 2026
        <description>

  * ``Salary`` reads ``"not specified"`` on most postings and a single figure
    (``\"₱20,000.00\"``) on some. The figure has no stated period, so it is
    stored with ``pay_period = monthly`` (the Philippine convention) and that
    guess is recorded in ``raw_payload``.
  * ``robots.txt`` returns HTTP 404, i.e. there is no robots file at all, so
    nothing is disallowed.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PhilJobNetSettings(BaseSettings):
    """Configuration for the PhilJobNet board (Philippines)."""

    model_config = SettingsConfigDict(env_prefix="PHILJOBNET_", extra="ignore")

    base_url: str = Field(default="https://philjobnet.gov.ph", description="Site root.")
    listing_path: str = Field(
        default="/job-vacancies/", description="Server-rendered listing page."
    )

    max_pages: int = Field(
        default=1, ge=1, le=200, description="Pages to walk. The board has no pager."
    )
    max_jobs_per_run: int = Field(
        default=50, ge=1, description="Cap on postings persisted in one run."
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)", description="Identifying UA."
    )
    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Detail pages are ~27 KB. 1.0s is comfortably inside what the site tolerates.
    inter_request_delay_seconds: float = Field(default=1.0, ge=0.0)

    fetch_description: bool = Field(
        default=True, description="Fetch each detail page for the body and metadata."
    )
    stop_after_repeated_empty_pages: int = Field(default=2, ge=1)
    min_links_per_page: int = Field(
        default=5, ge=1, description="Tail threshold. Pages carry ~10 postings."
    )
