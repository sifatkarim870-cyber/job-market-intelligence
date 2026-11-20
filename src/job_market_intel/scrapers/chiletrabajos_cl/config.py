"""Configuration for the Chiletrabajos (chiletrabajos.cl) scraper -- Chile.

Chiletrabajos is one of Chile's large generalist boards. It needs no key, no
registration and no proxy, and its advertised sitemap is the whole discovery
surface. The facts below come from the site's own files and ad markup; the
site could not be reached from this development network (TCP 80/443 time out
from Bangladesh while US, Canadian, Brazilian and German probes all get HTTP
200 from the same address), so the structure was read from archived captures
dated 2026-10-09 .. 2026-11-18 and end-to-end verification happens in CI
(GitHub Actions runs from the United States).

**robots.txt** (``/robots.txt``)::

    User-agent: *
    disallow: /partners/
    User-agent: Scrapy,proximic
    disallow: /
    Sitemap: https://www.chiletrabajos.cl/sitemap.xml
    User-agent:*
    Disallow:/ofertasmuchomas

The default ``*`` group disallows only ``/partners/`` and
``/ofertasmuchomas``, neither of which this scraper touches. There is no
``Crawl-delay`` for the default group; the ``Scrapy,proximic`` block is a
targeted bot ban, and this scraper does not send either token. A polite
one-second gap between requests is kept anyway.

**Discovery** is the advertised sitemap. Measured on 2026-10-09 it was a
single ``<urlset>`` of 32,993 ``/trabajo/<slug>-<id>`` URLs in newest-first
order (top ``lastmod`` 2026-10-09T03:29:15Z, bottom 2026-07-26), ~9.0 MB.
Because the sitemap is ordered newest-first, the top of the file is the
freshness window and a positional slice further down is the archive.

**Content** is one request per ad. Every ``/trabajo/`` page carries a
Schema.org ``JobPosting`` JSON-LD block among three blocks (the other two
are a ``BreadcrumbList`` and a related-ads ``ItemList``), and that block
holds the title, employer, ``datePosted``, ``validThrough``,
``employmentType``, ``industry``, ``jobLocation.address`` and the plain-text
description. There is no separate listing stage, so a 500-row run costs one
sitemap request plus 500 detail requests.

**Freshness / coverage.** The newest ``fresh_rows`` entries are always
taken, so a run never misses what was just posted. The rest of the budget
comes from a window that advances one budget-width per calendar day over
the tail of the sitemap, so older ads are covered over successive runs
instead of the same first page being re-read forever. ``start_offset``
pins that window for a reproducible run.

**Age of the sitemap.** The board prunes older ads from the sitemap (the
measured 32,993 URLs stop at 2026-07-26), so a URL that has already been
removed simply disappears from discovery; the stored rows are unaffected.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ChiletrabajosClSettings(BaseSettings):
    """Runtime configuration for the Chiletrabajos (Chile) scraper."""

    model_config = SettingsConfigDict(
        env_prefix="CHILETRABAJOS_CL_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(default="https://www.chiletrabajos.cl", description="Site root.")
    sitemap_url: str = Field(
        default="https://www.chiletrabajos.cl/sitemap.xml",
        description="Advertised sitemap used for discovery.",
    )
    job_url_template: str = Field(
        default="https://www.chiletrabajos.cl/trabajo/{slug}",
        description="Canonical ad URL; the sitemap's own <loc> is used verbatim.",
    )

    max_jobs_per_run: int = Field(
        default=500,
        ge=1,
        description="Cap on detail pages fetched and postings persisted in one run.",
    )
    #: The newest rows are always taken, so a run never misses what was just
    #: posted. The rest of the budget comes from a window that moves with the
    #: calendar (see ``start_offset``), so the older tail is covered over time.
    fresh_rows: int = Field(
        default=120,
        ge=0,
        description="Newest sitemap entries always sampled, ahead of the rotating window.",
    )
    #: ``None`` = derive the window start from today's date, advancing one
    #: budget-width per day. Pinning this makes a run reproducible (tests use
    #: it); CI leaves it unset.
    start_offset: int | None = Field(
        default=None,
        ge=0,
        description="Override for the rotating window start.",
    )

    fetch_details: bool = Field(
        default=True,
        description="Fetch each ad page for its JobPosting block. A run is useless "
        "without it, but the switch keeps offline tests honest.",
    )

    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        description="Browser user agent; the board's robots.txt bans Scrapy/proximic, not this.",
    )
    request_timeout_seconds: float = Field(default=45.0, gt=0)
    sitemap_timeout_seconds: float = Field(
        default=180.0,
        gt=0,
        description="The sitemap was ~9 MB on 2026-10-09, so it gets a longer budget.",
    )
    max_sitemap_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
        description="Refuse an outsized sitemap rather than buffering it indefinitely.",
    )
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: No Crawl-delay is advertised for the default group. One second keeps a
    #: 500-detail run around nine minutes while staying polite to a small board.
    inter_request_delay_seconds: float = Field(default=1.0, ge=0.0)
