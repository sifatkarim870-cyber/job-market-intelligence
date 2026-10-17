"""Configuration for the Angola Emprego scraper (Angola).

Measured on the live site on 2026-10-18 rather than assumed:

  * **Discovery** is ``/vagas?page=N``. Exactly **15** posting links per page,
    and the pager is real: ``?page=2`` returned **15 new** paths.

  * robots.txt is real ``text/plain`` (460 bytes) and is the interesting part:
    the ``User-agent: *`` group is ``Allow: /`` and disallows ``/login``,
    ``/register``, ``/perfil``, ``/planos``, ``/pagamento``,
    ``/vagas-sugeridas``, ``/linkstorage``, ``/auth/`` and -- crucially --
    three **query-parameter searches on the listing path**:

        Disallow: /vagas?q=
        Disallow: /vagas?location=
        Disallow: /vagas?category=
        Disallow: /?s=

    Those are the site's own duplicate-content rules, and they are why
    discovery walks ``?page=N`` rather than filtering by query. ``?page=`` is
    not among the disallowed parameters, so the pager is compliant.

  * Detail pages carry a schema.org ``JobPosting`` in a ``<script
    type="application/ld+json">`` block. The parser attempts a plain
    ``json.loads`` first and falls back to ``strict=False``.

Two traps in the payload, each measured:

  1. ``employmentType`` is a **list** (``["FULL_TIME"]``), not the bare string
     every other source in this project uses. A cleaner that does
     ``value.strip()`` raises ``AttributeError`` and drops every posting.
  2. ``identifier`` is a ``PropertyValue`` whose ``value`` is a **slug string**,
     not an int and not the numeric URL suffix -- some slugs end ``-4818`` and
     others do not, so the URL slug is the only reliable key.

There is **no ``baseSalary``** on any measured posting.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AngolaEmpregoSettings(BaseSettings):
    """Configuration for the Angola Emprego job board."""

    model_config = SettingsConfigDict(env_prefix="ANGOLA_EMPREGO_", extra="ignore")

    base_url: str = Field(default="https://angolaemprego.com", description="Site root.")
    listing_path: str = Field(default="/vagas", description="Server-rendered listing page.")

    max_pages: int = Field(
        default=8,
        ge=1,
        le=200,
        description=(
            "Listing pages to walk. 15 postings per page, so 8 pages is ~120. "
            "Measured to paginate cleanly with 15 new paths per page."
        ),
    )

    max_jobs_per_run: int = Field(
        default=120,
        ge=1,
        description="Cap on postings persisted in one run (ANGOLA_EMPREGO_MAX_JOBS_PER_RUN).",
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA. No key or registration is involved.",
    )

    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Detail pages are ~57 KB. 1.5s is comfortably inside what the site
    #: tolerates; no throttle was observed at this rate.
    inter_request_delay_seconds: float = Field(default=1.5, ge=0.0)

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
            "Stop after this many consecutive pages yield no new posting. The "
            "pager is real, so this guards against it regressing to static."
        ),
    )

    min_links_per_page: int = Field(
        default=5,
        ge=1,
        description=(
            "A page with fewer links than this is treated as the tail -- its "
            "links are still collected first. Pages carry 15."
        ),
    )
