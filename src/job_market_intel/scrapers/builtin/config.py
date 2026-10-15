"""Configuration for the Built In scraper (builtin.com).

Established by probing the live site on 2026-10-15, not assumed:

  * **Detail pages carry no ``JobPosting`` at the top level of their JSON-LD.**
    The block is an 8.8 KB document whose nodes live under an ``@graph`` key, so
    a parser that checks ``json["@type"]`` finds nothing and reports an empty
    board. The parser walks the whole document instead. This is the single
    biggest trap on this source.

  * Discovery paginates on ``/jobs?page=N``: 182 distinct job links over 8 pages,
    with the pager offering up to 1000. Pages are smaller than Wellfound's
    (20-27 links against 45-58), so the page cap is set a little higher.

  * Job URLs are ``/job/<slug>/<numeric id>`` -- the id is at the **end**, and
    the slug changes whenever the title is edited, so only the id is identity.

  * ``jobLocation`` is a single ``Place`` dict on 10 of 12 postings and a list
    on the other 2. Both are accepted.

  * ``jobBenefits`` is always a **list of strings** ("Offers 401(K)"), not the
    prose Wellfound puts in the same field.

  * ``jobLocationType`` is ``"TELECOMMUTE"`` on remote roles and ``null``
    otherwise, which is the only explicit remote flag on this board.

Compliance
----------
robots.txt is real ``text/plain`` (7.8 KB). Its relevant rules for
``User-agent: *``::

    Disallow: /search/
    Disallow: /jobs*?search=
    Disallow: *?page=
    Allow:    /jobs*?page=
    Disallow: /apply/
    Disallow: /taxonomy/

So keyword search is off limits and must not be used for discovery; plain
``/jobs`` and ``/jobs/<slug>`` paths are permitted, and ``?page=`` on a
``/jobs`` path is permitted because the ``Allow`` is the longer, more specific
match (RFC 9309 longest-match). Nothing in this scraper touches ``/search/``
or ``/jobs*?search=``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BuiltInSettings(BaseSettings):
    """Configuration for the Built In tech job board."""

    model_config = SettingsConfigDict(env_prefix="BUILTIN_", extra="ignore")

    base_url: str = Field(default="https://builtin.com", description="Site root.")

    #: Listing pages to walk. Deliberately paths only -- ``?search=`` is
    #: disallowed by robots.txt, so discovery cannot be keyword-driven.
    #: ``/jobs/remote`` is a facet page, not a search.
    listing_paths: list[str] = Field(
        default_factory=lambda: [
            "/jobs",
            "/jobs/remote",
            "/jobs/data-science",
            "/jobs/software-engineering",
            "/jobs/product-management",
            "/jobs/design",
            "/jobs/marketing",
            "/jobs/sales",
            "/jobs/project-management",
        ],
        description=(
            "Server-rendered listing pages. Never add a ?search= path: robots.txt disallows it."
        ),
    )

    max_pages_per_listing: int = Field(
        default=3,
        ge=1,
        le=100,
        description=(
            "Pages per listing. One page is 20-27 distinct jobs and costs a "
            "400 KB download, so this is the request-budget knob. The pager "
            "offers up to page 1000."
        ),
    )

    max_jobs_per_run: int = Field(
        default=300,
        ge=1,
        description="Cap on postings persisted in one run (BUILTIN_MAX_JOBS_PER_RUN).",
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA. No key or registration is involved.",
    )

    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Listing pages are 230-400 KB and detail pages 85-120 KB.
    inter_request_delay_seconds: float = Field(default=1.5, ge=0.0)

    fetch_description: bool = Field(
        default=True,
        description=(
            "Fetch each detail page for the JSON-LD block. Listing pages carry "
            "only a slug and an id, so without this there is nothing to store."
        ),
    )

    stop_after_repeated_empty_pages: int = Field(default=2, ge=1)

    min_links_per_page: int = Field(
        default=5,
        ge=1,
        description=(
            "A page with fewer links than this is treated as the tail, and its "
            "links are still collected before stopping. Built In pages carry "
            "20-27 links normally, so 5 is well clear of normal and only trips "
            "on a genuinely short final page."
        ),
    )
