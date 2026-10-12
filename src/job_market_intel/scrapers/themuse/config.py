"""Config for The Muse scraper.

The Muse (https://www.themuse.com) publishes employer-authored postings through
a free, key-free JSON API:

    GET https://www.themuse.com/api/public/jobs?page=<n>&page_size=<n>

Why this source
---------------
This is the largest untapped source measured. Probing on 2026-10-12 showed
``page_count = 20,694`` at 20 records per page -- roughly 400,000 postings,
against a current corpus of 114,734 rows. Nothing else on the free tier comes
close, and the postings are written by the employers themselves rather than
aggregated, so the description text is first-party.

The feed is NOT time-ordered. Across the first three pages the
``publication_date`` values ranged from 2025-01-17 to 2026-10-03, so paging
through it yields a mixture of fresh and long-expired postings. That is why
``max_pages_per_run`` is small and why ``min_publication_date`` exists: an
unbounded walk of this API is mostly a way to import two-year-old healthcare
vacancies into a job-market dataset.

Pagination is page-based here (unlike Himalayas, which ignores ``page``), and
``page_size`` is honoured up to 100.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ThemuseSettings(BaseSettings):
    """Runtime knobs for The Muse scraper (env prefix ``THEMUSE_``)."""

    model_config = SettingsConfigDict(
        env_prefix="THEMUSE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_url: str = Field(default="https://www.themuse.com", description="API host.")
    jobs_path: str = Field(default="/api/public/jobs", description="List endpoint path.")
    user_agent: str = Field(
        default="Mozilla/5.0 (compatible; job-market-intel/1.0)",
        description="Sent on every request.",
    )
    page_size: int = Field(
        default=50, ge=1, le=100, description="Records requested per page."
    )
    max_pages_per_run: int = Field(
        default=3,
        ge=1,
        description=(
            "Pages walked per run. Kept small deliberately: the feed is not "
            "time-ordered, so each additional page is mostly more historical "
            "postings rather than more current ones."
        ),
    )
    #: Postings older than this are dropped client-side. The API offers no date
    #: filter, and sampling showed publication dates spanning 2025-01 to
    #: 2026-10 on the FIRST THREE PAGES, so without this the scraper imports
    #: long-expired vacancies.
    max_age_days: int = Field(
        default=45, ge=1, description="Drop postings published longer ago than this."
    )
    max_jobs_per_run: int = Field(
        default=150, ge=1, description="Hard ceiling on postings persisted."
    )
    request_timeout_seconds: float = Field(
        default=25.0, gt=0, description="Per-request timeout."
    )
    max_retries: int = Field(default=3, ge=0, description="Attempts per request.")
    retry_backoff_seconds: float = Field(
        default=1.5, gt=0, description="Base delay for exponential backoff."
    )
