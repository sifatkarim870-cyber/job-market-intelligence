"""Config for the Jobicy scraper.

Jobicy (https://jobicy.com) publishes remote jobs through a free, key-free
JSON API:

    GET https://jobicy.com/api/v2/remote-jobs?count=<n>&tag=<tag>&geo=<geo>

Why this source
---------------
The corpus has exactly one remote-first board at scale (remoteok, 467 rows)
next to two dense country-specific boards. Jobicy adds a second remote view
with a field mix nothing else provides: ``jobGeo`` is a normalised region
(USA / UK / Europe / LATAM / APAC) rather than a city, and ``jobLevel`` plus
``jobType`` come as controlled vocabularies, so they map onto
``ref.experience_levels`` and the employment-type lookup without fuzzy
matching.

Pagination: there is none. Probing on 2026-10-12 showed ``page`` is rejected
outright (HTTP 400), and ``count`` silently caps at 200 -- count=200 and
count=500 both returned exactly 200. So one run is one request, optionally
narrowed by ``tag`` or ``geo``, and widening coverage means adding queries
rather than adding pages.

The feed is small and refreshed daily (every sampled record carried a
``pubDate`` of 2026-10-11), so ``max_jobs_per_run`` is a safety cap rather than
a real throttle.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobicySettings(BaseSettings):
    """Runtime knobs for the Jobicy scraper (env prefix ``JOBICY_``)."""

    model_config = SettingsConfigDict(
        env_prefix="JOBICY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_url: str = Field(default="https://jobicy.com", description="API host.")
    jobs_path: str = Field(default="/api/v2/remote-jobs", description="List endpoint.")
    user_agent: str = Field(
        default="Mozilla/5.0 (compatible; job-market-intel/1.0)",
        description="Sent on every request.",
    )
    #: The API caps this silently at 200 -- count=500 also returns 200 -- so
    #: asking for more does not error, it just does not deliver, and a run
    #: summary claiming 500 fetched would be a lie.
    page_size: int = Field(
        default=100, ge=1, le=200, description="Records requested per call."
    )
    #: Optional narrowings. Empty means "the whole feed", which is the default
    #: and is only about 200 records -- small, so widening is not the goal.
    tags: list[str] = Field(
        default_factory=list,
        description="Tag filters applied as separate requests (e.g. python, aws).",
    )
    geos: list[str] = Field(
        default_factory=list,
        description="Geo filters applied as separate requests (e.g. USA, Europe).",
    )
    max_requests_per_run: int = Field(
        default=1,
        ge=1,
        description=(
            "How many tag/geo queries to issue. 1 with no filters is the whole "
            "feed; raise it only alongside explicit tags/geos, or the extra "
            "requests return the same unfiltered page."
        ),
    )
    max_jobs_per_run: int = Field(
        default=200, ge=1, description="Hard ceiling on postings persisted."
    )
    request_timeout_seconds: float = Field(
        default=25.0, gt=0, description="Per-request timeout."
    )
    max_retries: int = Field(default=3, ge=0, description="Attempts per request.")
    retry_backoff_seconds: float = Field(
        default=1.5, gt=0, description="Base delay for exponential backoff."
    )
    #: Industries kept by default. The feed is mixed; this keeps the corpus on
    #: the technical roles it analyses. Empty disables the filter.
    focus_industries: list[str] = Field(
        default_factory=lambda: [
            "software",
            "data science",
            "information technology",
            "engineering",
            "design",
            "devops",
        ],
        description="Case-insensitive substrings matched against jobIndustry.",
    )
