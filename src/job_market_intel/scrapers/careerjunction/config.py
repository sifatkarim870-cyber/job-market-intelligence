"""Configuration for the CareerJunction scraper (South Africa).

Measured on the live site on 2026-10-17 rather than assumed:

  * **Discovery** is ``/jobs``. Exactly **25** links per page, shape
    ``/<slug>-job-<id>.aspx``. The pager is **ignored**: ``?page=2`` returns
    the same 25 links as page 1, so only one page is walked.

  * robots.txt is real ``text/plain`` (128 bytes). The governing ``*`` group is
    ``Allow: /``, disallowing only ``/myprofile/applied-jobs`` and
    ``/myprofile/EditProfile``. ``/jobs`` and ``/<slug>-job-<id>.aspx`` are
    permitted.

  * Detail pages carry a schema.org ``JobPosting`` in a ``<script
    type="application/ld+json">`` block, but the JSON is **malformed**: the
    ``description`` string contains raw newlines and HTML entities, which makes
    ``json.loads`` raise ``Invalid control character``. The fix is
    ``json.loads(block, strict=False)``, which tolerates control characters
    inside strings. Every field extracts cleanly that way.

  * The payload has no ``identifier`` and no real ``baseSalary`` (the value is
    ``"R Undisclosed"``). The id comes from the URL, and there is no salary to
    map.

  * ``datePosted`` / ``validThrough`` are formatted ``"2026/10/16 10:33:33 AM"``
    -- not ISO 8601. A custom date parser handles this.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CareerJunctionSettings(BaseSettings):
    """Configuration for the CareerJunction South Africa job board."""

    model_config = SettingsConfigDict(env_prefix="CAREERJUNCTION_", extra="ignore")

    base_url: str = Field(default="https://www.careerjunction.co.za", description="Site root.")
    listing_path: str = Field(default="/jobs", description="Server-rendered listing page.")

    max_pages: int = Field(
        default=1,
        ge=1,
        le=200,
        description=(
            "Listing pages to walk. The pager is ignored (?page=2 returns the "
            "same 25 links), so only one page is walked."
        ),
    )

    max_jobs_per_run: int = Field(
        default=25,
        ge=1,
        description="Cap on postings persisted in one run (CAREERJUNCTION_MAX_JOBS_PER_RUN).",
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA. No key or registration is involved.",
    )

    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Detail pages are 80-90 KB. 1.0s keeps a 25-posting run around 1 minute.
    inter_request_delay_seconds: float = Field(default=1.0, ge=0.0)

    fetch_description: bool = Field(
        default=True,
        description=(
            "Fetch each detail page for the JSON-LD block. Listing pages carry "
            "only a path, so without this there is nothing to store."
        ),
    )

    stop_after_repeated_empty_pages: int = Field(
        default=2,
        ge=1,
        description=(
            "Stop after this many consecutive pages yield no new posting id. "
            "Kept as a guard even though only one page is walked."
        ),
    )

    min_links_per_page: int = Field(
        default=5,
        ge=1,
        description=(
            "A page with fewer links than this is treated as the tail -- its "
            "links are still collected first. Pages carry 25."
        ),
    )
