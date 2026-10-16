"""Configuration for the Net-Empregos scraper (Portugal).

Measured on the live site on 2026-10-16 rather than assumed:

  * **Discovery** is ``/jobs?page=N``. Exactly **18** links per page, and the
    pager is real: 18 new ids on every page. The URL pattern is
    ``/jobs/<id>/<slug>/`` where the id is 6-12 digits.

  * robots.txt returns **HTTP 406 as text/html** -- not a real robots file, so
    under RFC 9309 there is no restriction to parse. ``/jobs`` and
    ``/jobs/<id>/<slug>/`` are both fetchable.

  * Detail pages carry a schema.org ``JobPosting`` in a ``<script
    type="application/ld+json">`` block, but the JSON is **malformed**: the
    ``description`` string contains raw newlines, which makes ``json.loads``
    raise ``Invalid control character``. The fix is ``json.loads(block,
    strict=False)``, which tolerates control characters inside strings. Every
    field extracts cleanly that way.

  * The payload has no ``identifier`` and no ``baseSalary``. The id comes from
    the URL, and there is no salary to map.

  * ``addressCountry`` is the ISO code ``"PT"``, and ``datePosted`` /
    ``validThrough`` are formatted ``"2026-10-16 21:47 UTC"``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class NetEmpregosSettings(BaseSettings):
    """Configuration for the Net-Empregos Portugal job board."""

    model_config = SettingsConfigDict(env_prefix="NET_EMPREGOS_", extra="ignore")

    base_url: str = Field(default="https://www.net-empregos.com", description="Site root.")
    listing_path: str = Field(default="/jobs", description="Server-rendered listing page.")

    max_pages: int = Field(
        default=8,
        ge=1,
        le=200,
        description=(
            "Listing pages to walk. 18 postings per page, so 8 pages is ~144. "
            "Measured to paginate cleanly."
        ),
    )

    max_jobs_per_run: int = Field(
        default=150,
        ge=1,
        description="Cap on postings persisted in one run (NET_EMPREGOS_MAX_JOBS_PER_RUN).",
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA. No key or registration is involved.",
    )

    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Detail pages are 80-90 KB. 1.0s keeps a 150-posting run around 5 minutes.
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
            "Guards the case where the listing ignores ?page=."
        ),
    )

    min_links_per_page: int = Field(
        default=5,
        ge=1,
        description=(
            "A page with fewer links than this is treated as the tail -- but its "
            "links are still collected first, because a short final page still "
            "holds real postings. Pages carry 18."
        ),
    )
