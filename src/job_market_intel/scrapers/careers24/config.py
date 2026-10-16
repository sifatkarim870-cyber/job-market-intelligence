"""Configuration for the Careers24 scraper (South Africa).

Established by probing the live site on 2026-10-15, not assumed:

  * **Discovery** is ``/jobs?page=N``. Pages hold **10** adverts each and
    genuinely paginate: 54 distinct advert ids across 6 pages, with the
    id set changing every page. Do not assume 50-per-page like Wellfound.

  * Detail URLs are ``/jobs/adverts/<id>-<slug>`` and the hrefs carry a query
    string (``?jobindex=2``). A regex that stops at the slug without allowing
    a following ``?`` matches nothing at all -- which is what happened on the
    first two probe passes, and briefly made a working board look empty.

  * Detail pages carry a schema.org ``JobPosting`` with 12 of 12 fields present
    on all 8 postings measured: title, description, industry, identifier,
    datePosted, validThrough, employmentType, hiringOrganization, jobLocation.
    ``baseSalary`` was on 2 of those 8; a wider run over 40 postings found 15
    of 40, all in the ``value.value`` shape described in :mod:`.parser`.

  * **The salary nests one level deeper than the sibling sources.**
    Careers24 emits ``{"currency": "ZAR", "value": {"@type":
    "QuantitativeValue", "value": "180", "unitText": "DAY"}}`` -- the figure is
    under ``value.value`` and there is no ``minValue``/``maxValue`` at all. A
    parser written for Wellfound's or Built In's band reads ``None`` for both
    bounds, silently, and the first implementation of this scraper did exactly
    that: it recorded a salary for 0 of 40 postings that 15 of 40 publish.
    Measured periods: yearly 10, monthly 3, daily 1, and one posting with an
    empty ``unitText``.

Compliance
----------
robots.txt is real ``text/plain`` (646 bytes) and lists ~16 named user-agent
groups (Scrapy, Yandex, Baiduspider, SemrushBot, ...), several of which carry
``Disallow: /``.

**There is no ``User-agent: *`` group.** Under RFC 9309 that means the crawler
is not subject to any rule in the file, and ``robots.txt`` imposes no
restriction here. This is worth stating explicitly rather than inferred: it is
the only board in this project where the governing group is absent rather than
permissive, and a naive "find the * group, find nothing, assume blocked"
reading would discard the source. ``urllib.robotparser`` agrees and reports
``/jobs`` and ``/jobs/adverts/...`` as fetchable.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Careers24Settings(BaseSettings):
    """Configuration for the Careers24 South Africa job board."""

    model_config = SettingsConfigDict(env_prefix="CAREERS24_", extra="ignore")

    base_url: str = Field(default="https://www.careers24.com", description="Site root.")
    listing_path: str = Field(default="/jobs", description="Server-rendered listing page.")

    max_pages: int = Field(
        default=10,
        ge=1,
        le=200,
        description=(
            "Listing pages to walk. 10 adverts per page, so 10 pages is ~100 "
            "postings; the site's own pager runs well past that."
        ),
    )

    max_jobs_per_run: int = Field(
        default=200,
        ge=1,
        description="Cap on postings persisted in one run (CAREERS24_MAX_JOBS_PER_RUN).",
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA. No key or registration is involved.",
    )

    request_timeout_seconds: int = Field(default=45, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Listing pages are ~316 KB and detail pages ~46 KB. 1.2s is polite
    #: without making a 200-posting run take 20 minutes.
    inter_request_delay_seconds: float = Field(default=1.2, ge=0.0)

    fetch_description: bool = Field(
        default=True,
        description=(
            "Fetch each detail page for the JSON-LD block. The listing page "
            "carries only an id, a slug and a ?jobindex= rank -- no title, no "
            "company, no description -- so without this there is nothing to store."
        ),
    )

    stop_after_repeated_empty_pages: int = Field(
        default=2,
        ge=1,
        description=(
            "Stop after this many consecutive pages yield no new advert id. "
            "Guards the case where a listing path is added that ignores its "
            "page parameter -- the /jobs?page=N failure measured on Wellfound."
        ),
    )

    min_links_per_page: int = Field(
        default=3,
        ge=1,
        description=(
            "A page with fewer adverts than this is treated as the tail -- but "
            "its adverts are still collected first, because a short final page "
            "still holds real postings. Pages normally carry 10."
        ),
    )
