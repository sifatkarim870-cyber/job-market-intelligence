"""Config for the Himalayas scraper.

Himalayas (https://himalayas.app) aggregates remote-friendly postings and
publishes a free, key-free JSON API:

    GET https://himalayas.app/jobs/api?limit=<n>&offset=<n>

Why this source
---------------
The corpus already leans heavily on jobvision (61,019 rows) and jobinja
(16,891). Both are country-specific and dense, so the marginal value of another
country-specific board is limited. Himalayas is a *remote-first aggregator*
spanning many employers, which adds the company dimension the corpus is
thinnest on, and it reports salary, seniority and categories -- three fields
most free boards omit, and three this project already has columns for.

Pagination is OFFSET-based, not page-based. Probing on 2026-10-12 showed that
passing ``page`` is silently IGNORED: offset 0 and page 1 returned byte-identical
first results, and only ``offset`` advanced the window. That is an easy way to
write a scraper that re-fetches the same 20 jobs every run and looks healthy
while inserting nothing.

IDs are taken from ``guid`` (the canonical job URL) rather than a numeric id,
because the numeric id is not present in the list payload at all -- only in the
per-job endpoint. ``guid`` is stable and unique per posting, which is what the
natural key ``(source_id, source_job_id, posting_date)`` needs.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HimalayasSettings(BaseSettings):
    """Runtime knobs for the Himalayas scraper (env prefix ``HIMALAYAS_``)."""

    model_config = SettingsConfigDict(
        env_prefix="HIMALAYAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_url: str = Field(default="https://himalayas.app", description="API host.")
    jobs_path: str = Field(default="/jobs/api", description="List endpoint path.")
    user_agent: str = Field(
        default="Mozilla/5.0 (compatible; job-market-intel/1.0)",
        description="Sent on every request; the API rejects some default agents.",
    )
    page_size: int = Field(
        default=20,
        ge=1,
        le=20,
        description=(
            "Records requested per page. The API IGNORES a larger value and "
            "silently returns 20 -- probed 2026-10-12, where limit=20, 50, 100 "
            "and 200 each came back with exactly 20 records. The ceiling here "
            "is 20 so the short-page check compares like with like instead of "
            "reading the cap as the end of the feed."
        ),
    )
    max_pages_per_run: int = Field(
        default=3,
        ge=1,
        description=(
            "Offset windows walked per run. Each is one HTTP request, and the "
            "remote job board is small enough that a large number mostly "
            "re-fetches rows already stored."
        ),
    )
    max_jobs_per_run: int = Field(
        default=150,
        ge=1,
        description="Hard ceiling on postings persisted in a single run.",
    )
    request_timeout_seconds: float = Field(
        default=25.0, gt=0, description="Per-request timeout."
    )
    max_retries: int = Field(
        default=3, ge=0, description="Attempts per request before giving up."
    )
    retry_backoff_seconds: float = Field(
        default=1.5, gt=0, description="Base delay for exponential backoff."
    )
    #: Tags that keep the corpus on the technical side it is built around.
    #: Unfiltered, the feed is dominated by healthcare and support roles, which
    #: are legitimate postings but are not what this dataset analyses.
    focus_categories: list[str] = Field(
        default_factory=lambda: [
            "Engineering",
            "Information Technology",
            "Software",
            "Data Science",
            "Design",
            "Product",
        ],
        description=(
            "parentCategories to keep, case-insensitive. Empty list disables the "
            "filter and keeps everything."
        ),
    )
