"""Configuration for the Mustakbil scraper (Pakistan).

Measured on the live site on 2026-10-16 rather than assumed:

  * **Discovery is breadth-by-category, not pagination.** ``/jobs`` returns 43
    posting ids and ``/jobs?page=2`` is **byte-identical** -- 398,957 bytes both
    times, same 43 ids, 0 new. The ``page`` parameter is ignored, exactly like
    Wellfound's. Breadth has to come from walking category paths instead:
    ``/jobs/pakistan/<slug>``. Of 25 plausible category slugs, **8 exist** and
    17 return HTTP 404. The 8 working paths add 80 ids beyond the baseline, for
    **123 distinct postings** across the nine paths.

  * robots.txt (1,882 bytes, real ``text/plain``) has a ``User-agent: *`` group
    with ``Allow: /``, disallowing only ``/clearCache``, ``/clearcache`` and
    ``/content/images/ads/``. ``/jobs`` and ``/jobs/job/<id>`` are permitted. The
    named groups (SemrushBot, AhrefsBot, PetalBot, ...) mostly carry
    ``Disallow: /``, which does not apply to this crawler.

  * **The site rate-limits hard.** A burst of listing fetches is fine, but
    every *detail* fetch then fails with ``ConnectionError`` until a
    multi-minute cool-off. Measured: 3.5s between requests was not enough;
    75s of total quiet restored service. That is why the default delay here is
    4.0s -- roughly ten times the politest settings in this project, and not
    negotiable downwards without re-measuring.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MustakbilSettings(BaseSettings):
    """Configuration for the Mustakbil Pakistan job board."""

    model_config = SettingsConfigDict(env_prefix="MUSTAKBIL_", extra="ignore")

    base_url: str = Field(default="https://mustakbil.com", description="Site root.")

    #: The baseline listing. ``?page=`` is deliberately absent: it is ignored.
    listing_paths: list[str] = Field(
        default_factory=lambda: [
            "/jobs",
            "/jobs/pakistan/information-technology",
            "/jobs/pakistan/engineering",
            "/jobs/pakistan/healthcare",
            "/jobs/pakistan/sales",
            "/jobs/pakistan/education",
            "/jobs/pakistan/security",
            "/jobs/pakistan/pharmacy",
            "/jobs/pakistan/finance",
        ],
        description=(
            "Listing paths to walk. These 9 return HTTP 200 with job links; 17 "
            "other plausible slugs return 404 (measured 2026-10-16). Each path "
            "returns one page only -- there is no working pagination."
        ),
    )

    max_jobs_per_run: int = Field(
        default=120,
        ge=1,
        description=(
            "Cap on postings persisted in one run (MUSTAKBIL_MAX_JOBS_PER_RUN). "
            "The nine listing paths yield 123 distinct ids in total."
        ),
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA. No key or registration is involved.",
    )

    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=4, ge=1)
    retry_initial_wait_seconds: float = Field(default=5.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=45.0, ge=0.0)

    #: See the module docstring. 4.0s is measured, not guessed: at 3.5s the
    #: detail fetches still failed with ConnectionError after the listing burst.
    inter_request_delay_seconds: float = Field(default=4.0, ge=0.0)

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
            "Kept as a guard even though each path is single-page, because a "
            "listing path that stops working must not be walked to the cap."
        ),
    )

    min_links_per_page: int = Field(
        default=2,
        ge=1,
        description=(
            "A page with fewer links than this is treated as the tail -- its "
            "links are still collected first, because a small category ("
            "security had 2, pharmacy 4) still holds real postings."
        ),
    )
