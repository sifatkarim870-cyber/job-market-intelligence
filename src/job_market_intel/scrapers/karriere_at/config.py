"""Configuration for the Karriere.at scraper (Austria).

Measured on the live site on 2026-10-18 rather than assumed:

  * **Discovery** is ``/jobs`` with **no working pager**: ``?page=2`` returns 0
    new postings, so all **15** postings sit on one page. The whole board is a
    single request.
  * Hrefs are **absolute** (measured 15 absolute, 0 relative).
  * Detail pages carry a schema.org ``JobPosting``. Measured keys:
    ``title``, ``description`` (HTML), ``datePosted`` (with a timezone offset),
    ``employmentType`` (a **list**, ``[\"PART_TIME\"]``), ``hiringOrganization``
    (name + ``sameAs``), ``identifier`` (``PropertyValue``, value is a **string**),
    ``jobLocation`` (an **array** of ``Place``), ``baseSalary`` (EUR, nested
    ``value.value`` shape) and ``directApply``.
  * **No ``industry``** on the measured postings.

robots.txt: ``User-agent: *`` group is empty (allow all). Only ``BLEXBot`` and
``AhrefsBot`` are blocked.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KarriereAtSettings(BaseSettings):
    """Configuration for the Karriere.at board (Austria)."""

    model_config = SettingsConfigDict(env_prefix="KARRIERE_AT_", extra="ignore")

    base_url: str = Field(default="https://www.karriere.at", description="Site root.")
    listing_path: str = Field(default="/jobs", description="Server-rendered listing page.")

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

    #: Detail pages are ~316 KB. 1.5s is comfortably inside what the site tolerates.
    inter_request_delay_seconds: float = Field(default=1.5, ge=0.0)

    fetch_description: bool = Field(
        default=True, description="Fetch each detail page for the JSON-LD block."
    )
    stop_after_repeated_empty_pages: int = Field(default=2, ge=1)
    min_links_per_page: int = Field(
        default=5, ge=1, description="Tail threshold. Pages carry ~15 postings."
    )
