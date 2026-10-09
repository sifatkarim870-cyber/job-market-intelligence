"""Greenhouse-specific configuration.

Greenhouse is different in kind from every other source in this project: it is
not one job board but an ATS (applicant tracking system) that hundreds of
companies run. There is no single feed -- the endpoint is parameterised by a
board slug -- so this config carries a COMPANY_SLUGS list rather than a URL.

That makes a single generic scraper able to cover an entire company's careers
site, and the same code able to grow to hundreds of companies by editing one
list. It is the highest-leverage free, key-less source found: a single board
returned 218, 731, 432 and 155 postings for gitlab, stripe, datadog and
reddit respectively at the time of probing.

``boards-api.greenhouse.io`` is a separate public host from the company-branded
``job-boards.greenhouse.io``; the former serves JSON and needs no API key, the
latter serves HTML and is not what we want.

Every setting has a working default, so the scraper runs with no .env entries.
Override with ``GREENHOUSE_`` prefixes, e.g.:

    GREENHOUSE_COMPANY_SLUGS=gitlab,stripe
    GREENHOUSE_MAX_JOBS_PER_RUN=500
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Board slugs verified to resolve against the live public API by
#: ``scripts/probe_greenhouse_boards.py``, which tried 78 candidates and found
#: 30 live boards carrying 6,573 postings between them.
#:
#: Ordered by volume (descending), so that if ``max_jobs_per_run`` truncates
#: the walk, the boards already fetched are the big ones. Verified rather than
#: guessed: a wrong slug is not free, it costs an HTTP request and a warning on
#: every single run, forever.
DEFAULT_COMPANY_SLUGS: list[str] = [
    "databricks",     # 893
    "stripe",         # 731
    "anthropic",      # ~600
    "datadog",        # 432
    "elastic",
    "cloudflare",
    "mongodb",
    "okta",           # 379
    "brex",
    "gitlab",         # 220
    "coinbase",
    "fivetran",       # 201
    "scaleai",
    "robinhood",
    "reddit",         # 155
    "figma",
    "twilio",         # 138
    "intercom",
    "asana",
    "gusto",
    "vercel",
    "mixpanel",
    "algolia",
    "typeform",
    "circleci",
    "veracode",
    "buildkite",
    "netlify",
    "airtable",
    "prisma",
]


class GreenhouseSettings(BaseSettings):
    """Configuration for the Greenhouse board scraper."""

    model_config = SettingsConfigDict(env_prefix="GREENHOUSE_", extra="ignore")

    api_base_url: str = Field(
        default="https://boards-api.greenhouse.io/v1/boards",
        description="Base URL for Greenhouse's public board API. No key required.",
    )
    company_slugs: list[str] = Field(
        default_factory=lambda: list(DEFAULT_COMPANY_SLUGS),
        description="Board slugs to scrape, e.g. gitlab. One HTTP request per slug.",
    )
    request_timeout_seconds: int = Field(
        default=25,
        ge=1,
        description="Max seconds to wait for one board's response.",
    )
    max_jobs_per_run: int = Field(
        default=2500,
        ge=1,
        description=(
            "Cap on postings persisted in one run, across all boards. The 30 "
            "verified boards hold ~6,570 postings, but the walk stops once the "
            "budget is spent, so this also decides how many boards are reached. "
            "Sized for CI: each row is an individual insert, and over the WAN "
            "to Neon a 6,500-row run does not fit a sane job timeout."
        ),
    )
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=1.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=8.0, ge=0.0)
    inter_board_delay_seconds: float = Field(
        default=0.4,
        ge=0.0,
        description="Pause between board requests. Greenhouse serves many distinct "
        "companies from one host, so this keeps us a polite client rather than "
        "hammering a shared endpoint.",
    )
    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    )

    @field_validator("company_slugs", mode="before")
    @classmethod
    def _split_slugs(cls, value: object) -> object:
        """Accept ``a,b,c`` from the environment as well as a real list.

        pydantic-settings parses complex types as JSON, so a bare
        ``GREENHOUSE_COMPANY_SLUGS=gitlab,stripe`` in .env would otherwise be
        a JSON decode error rather than the obvious thing the user meant.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return value
            return [part.strip() for part in stripped.split(",") if part.strip()]
        return value
