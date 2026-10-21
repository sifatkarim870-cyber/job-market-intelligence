"""Configuration for the Shine.com scraper (India).

Measured on the live site on 2026-10-20 rather than assumed:

  * **Listing path.** ``/job-search/jobs-in-india`` returns 40 postings
    per page with real ``rel="next"`` pagination. The next page is
    ``/job-search/india-jobs-2``, then ``-3``, etc. The suffix is an
    integer appended to the base path, not a ?page= query.
  * **Detail path.** ``/jobs/<slug>/<company>/<numeric_id>``. The numeric
    id is the natural key and doubles as source_job_id.
  * **JSON-LD JobPosting** on the detail page carries every structured
    field: title, hiringOrganization, identifier.value, url, datePosted,
    validThrough, employmentType, experienceRequirements, jobLocation,
    skills, industry.
  * **No browser.** Plain HTTP returns full markup; Playwright is not
    needed and not used.
  * **No __NEXT_DATA__.** The Next.js app ships data in schema.org
    JSON-LD, not a hydration blob.
  * robots.txt: ``User-agent: *`` / ``Allow: /``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ShineSettings(BaseSettings):
    """Configuration for the Shine.com board (India)."""

    model_config = SettingsConfigDict(env_prefix="SHINE_", extra="ignore")

    base_url: str = Field(default="https://www.shine.com", description="Site root.")

    listing_path: str = Field(
        default="/job-search/jobs-in-india",
        description="Listing page, first page.",
    )
    listing_next_suffix: int = Field(
        default=2,
        ge=1,
        description="The listing paginates by appending -N to the path "
        "(india-jobs-2, india-jobs-3, ...), starting at 2.",
    )

    max_pages: int = Field(default=3, ge=1, le=100, description="Listing pages to walk.")
    max_jobs_per_run: int = Field(
        default=60, ge=1, description="Cap on postings persisted in one run."
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA.",
    )
    request_timeout_seconds: int = Field(default=30, ge=1, description="HTTP timeout.")
    inter_request_delay_seconds: float = Field(default=2.0, ge=0.0)
    detail_fetch_attempts: int = Field(default=3, ge=1, le=6)
    retry_backoff_seconds: float = Field(default=5.0, ge=0.0)
