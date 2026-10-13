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
#: ``scripts/probe_greenhouse_boards.py``. Expanded 2026-10-14 from 78
#: candidates to 502, which found 90 live boards carrying 10,470 postings
#: -- 66 boards (4,280 postings) not previously configured. Ordered by
#: posting count descending because ``max_jobs_per_run`` stops the walk once
#: its budget is spent, so the largest boards are always the ones reached.
#: A local full backfill should raise GREENHOUSE_MAX_JOBS_PER_RUN rather
#: than rely on the CI-sized default.
DEFAULT_COMPANY_SLUGS: list[str] = [
    "databricks",  # 894
    "stripe",  # 723
    "anthropic",  # 646
    "datadog",  # 439
    "cloudflare",  # 436
    "mongodb",  # 393
    "elastic",  # 381
    "okta",  # 379
    "zscaler",  # 366
    "verkada",  # 310
    "brex",  # 268
    "roblox",  # 258
    "samsara",  # 239
    "coinbase",  # 227
    "gitlab",  # 218
    "flexport",  # 205
    "scaleai",  # 183
    "ubiquiti",  # 180
    "lyft",  # 179
    "robinhood",  # 177
    "pinterest",  # 176
    "airbnb",  # 167
    "twilio",  # 146
    "reddit",  # 145
    "klaviyo",  # 145
    "figma",  # 143
    "anaplan",  # 137
    "rubrik",  # 137
    "roku",  # 124
    "instacart",  # 120
    "intercom",  # 108
    "asana",  # 103
    "mozilla",  # 95
    "kaseya",  # 94
    "vercel",  # 89
    "five9",  # 88
    "engine",  # 78
    "qualtrics",  # 70
    "duolingo",  # 59
    "jetbrains",  # 58
    "zocdoc",  # 58
    "newrelic",  # 55
    "pagerduty",  # 54
    "mixpanel",  # 53
    "commvault",  # 53
    "twitch",  # 52
    "discord",  # 47
    "checkr",  # 44
    "trustpilot",  # 44
    "lighthouse",  # 36
    "druva",  # 34
    "flex",  # 32
    "dropbox",  # 30
    "zuora",  # 29
    "slice",  # 27
    "nucleus",  # 25
    "pendo",  # 23
    "webflow",  # 23
    "contentful",  # 21
    "nextdoor",  # 21
    "udacity",  # 21
    "yext",  # 21
    "wise",  # 20
    "greenhouse",  # 18
    "trivago",  # 18
    "coursera",  # 16
    "yugabyte",  # 16
    "litmos",  # 15
    "vonage",  # 15
    "mattermost",  # 14
    "typeform",  # 13
    "circleci",  # 13
    "link",  # 13
    "skillsoft",  # 13
    "flipp",  # 11
    "wasabi",  # 10
    "platformsh",  # 9
    "sumologic",  # 9
    "upwork",  # 9
    "buildkite",  # 8
    "rstudio",  # 8
    "sendbird",  # 7
    "udemy",  # 7
    "netlify",  # 5
    "hootsuite",  # 4
    "clever",  # 3
    "liveperson",  # 3
    "method",  # 3
    "thrive",  # 3
    "staging",  # 1
    "fivetran",  # no longer resolving -- kept, see note
    "gusto",  # no longer resolving -- kept, see note
    "algolia",  # no longer resolving -- kept, see note
    "veracode",  # no longer resolving -- kept, see note
    "airtable",  # no longer resolving -- kept, see note
    "prisma",  # no longer resolving -- kept, see note
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
        default=1000,
        ge=1,
        description=(
            "Cap on postings persisted in one run, across all boards. The 30 "
            "verified boards hold ~6,570 postings, but the walk stops once the "
            "budget is spent, so this also decides how many boards are reached. "
            "Sized from measured CI throughput rather than guessed: greenhouse "
            "saves row-by-row, and commits 250 rows every 7.9-8.9 minutes "
            "against Neon, i.e. 1.98 s/row. Against the registry's 45-minute "
            "step timeout that puts the ceiling at ~1,360 rows, so the previous "
            "default of 2,500 needed 82 minutes and every scheduled run was "
            "killed at 45 -- committing its first 1,250 rows and discarding the "
            "rest. 1,000 leaves ~12 minutes of headroom for a slower runner. "
            "CI runs every 6 hours, so this still clears 4,000 rows/day; raise it "
            "via GREENHOUSE_MAX_JOBS_PER_RUN for a local full backfill."
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
