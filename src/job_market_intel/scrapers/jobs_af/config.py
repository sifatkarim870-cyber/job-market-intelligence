"""Configuration for the Jobs.af scraper (Afghanistan).

Measured on the live site on 2026-10-18 rather than assumed:

  * **Discovery** is the **homepage**, which links **12** postings shaped
    ``/public/job/<slug>``. There is **no working pager**: ``/public/job/page/2``
    is HTTP 404, ``/public/job?page=2`` adds 0 new, and re-fetching ``/`` adds 0
    new. So the whole board is a single request, like Job in Rwanda.

  * Detail pages carry a schema.org ``JobPosting``. Measured keys:
    ``title``, ``description``, ``datePosted``, ``validThrough``,
    ``employmentType`` (``"FULL_TIME"``, a bare string), ``hiringOrganization``
    (name + ``logo``), ``jobLocation`` (address with ``addressCountry``) and
    ``directApply``. **No ``identifier``** and **no ``baseSalary``**, so the URL
    slug is the key and no salary is stored.

Two traps, each measured:

  * ``addressCountry`` is the **name** ``"Afghanistan"``, not the ISO code
    ``"AF"``. The same shape as Vagas.com.br's ``"Brasil"``, and with the same
    consequence: an unmapped name resolves to no country, and the row collapses
    onto the global-remote location.

  * ``datePosted`` carries **milliseconds and a truncated offset**:
    ``"2026-10-17 10:48:27.175+00"``. That is not ISO 8601 (``+00`` is missing
    its minutes), so a strict ISO parser returns nothing for every posting.

robots.txt is real ``text/plain`` (661 bytes): ``User-Agent: *`` is ``Allow: /``
and disallows only ``/dashboard``, ``/discover``, ``/talents``, ``/projects`` and
``/wallet``. ``/public/job/`` is permitted.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobsAfSettings(BaseSettings):
    """Configuration for the Jobs.af Afghan job board."""

    model_config = SettingsConfigDict(env_prefix="JOBS_AF_", extra="ignore")

    base_url: str = Field(default="https://jobs.af", description="Site root.")
    listing_path: str = Field(
        default="/",
        description=(
            "The homepage is the listing: /public/job/page/2 is HTTP 404 and "
            "?page=2 adds nothing, so all postings are on one page."
        ),
    )

    max_pages: int = Field(
        default=1,
        ge=1,
        le=200,
        description=(
            "Pages to walk. The pager does not exist, so this is 1 -- kept as a "
            "knob so a future pager is a config change rather than a rewrite."
        ),
    )

    max_jobs_per_run: int = Field(
        default=50,
        ge=1,
        description="Cap on postings persisted in one run (JOBS_AF_MAX_JOBS_PER_RUN).",
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA. No key or registration is involved.",
    )

    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Detail pages are ~45 KB. 1.5s is comfortably inside what the site
    #: tolerates; no throttle was observed.
    inter_request_delay_seconds: float = Field(default=1.5, ge=0.0)

    fetch_description: bool = Field(
        default=True,
        description=(
            "Fetch each detail page for the JSON-LD block. The homepage carries "
            "only a path, so without this there is nothing to store."
        ),
    )

    stop_after_repeated_empty_pages: int = Field(default=2, ge=1)
    min_links_per_page: int = Field(
        default=5,
        ge=1,
        description="Tail threshold. The homepage carries 12 postings.",
    )
