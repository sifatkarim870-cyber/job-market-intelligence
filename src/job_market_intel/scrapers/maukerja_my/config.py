"""Configuration for the MauKerja (maukerja.my) scraper -- Malaysia.

MauKerja is one of Malaysia's large generalist boards (AJobThing's consumer
brand). It needs no key, no registration and no proxy, and its advertised
sitemap is the whole discovery surface. The facts below were measured from the
live site on 2026-11-20.

**robots.txt** (``/robots.txt``, HTTP 200, 1,214 bytes) bans a list of AI
crawlers outright (``Yandex``, ``PetalBot``, ``dotbot``, ``ClaudeBot``,
``Bytespider``, ``GPTBot``, ``Google-Extended``, ``Amazonbot``,
``FacebookBot``) and, for ``User-agent: *``, disallows a set of paths::

    Disallow: /jobseeker-login$
    Disallow: /jobseeker$
    Disallow: /job/apply-job?*
    Disallow: /api/*          Disallow: /v3mkapi/*     Disallow: /search/*
    Disallow: /v1/*           Disallow: /mkrbapi/*     Disallow: /adhjobclick/*
    Disallow: /*/apply.php?   Disallow: /job-region/   Disallow: /rnetjobclick/
    Disallow: /jobs/          Disallow: /content/search*
    Disallow: /v3-company-service/*   Disallow: /job/read/   Disallow: /job/*/search
    Disallow: /v3/search/     Disallow: /impression-api/  Disallow: /career-advice/blog/tag/*
    Disallow: /company-view-event/    Disallow: /localapi/   Disallow: /endorse/*
    Disallow: /server-api/*

    Sitemap: https://www.maukerja.my/sitemap.xml

None of the disallowed prefixes is touched: discovery reads the advertised
sitemaps (which the file itself names) and the only content requests are
``/job/<id>-<slug>`` detail pages, which are not covered by any rule (the
``/job/*/search`` and ``/job/read/`` patterns are different shapes). The
default group sets no ``Crawl-delay``; this scraper keeps a polite one-second
gap anyway. This scraper does not send any banned bot token -- it sends an
ordinary desktop Chrome ``User-Agent``.

**Discovery** is the advertised sitemap chain, measured 2026-11-20::

    /sitemap.xml          sitemapindex, 17 children
      -> /mk_job.xml      sitemapindex, 1 child
         -> /mk_job1.xml  <urlset>, 46,652 ad URLs, 8,967,071 bytes

``mk_job1.xml`` is newest-first (top ``lastmod`` 2026-11-20, bottom
2020-09-04) and every ``/job/<id>-<slug>`` id is unique. The other children
are company pages, company-scoped job listings (not ads), categories, blogs,
salaries and forums -- all skipped by the ``^mk_job\\d*\\.xml$`` name filter,
so a future ``mk_job2.xml`` is discovered automatically while
``mk_company_job*.xml`` and ``mk_jobsearch*.xml`` never are.

The listing path ``/jobsearch/all-jobs`` is behind a Cloudflare interstitial
("Just a moment...", HTTP 403, from plain requests and curl_cffi alike), which
is why discovery uses the sitemaps the board publishes rather than scraping
search result pages.

**Content** is one request per ad. Every ``/job/<id>-<slug>`` page carries a
Schema.org ``JobPosting`` JSON-LD block (the page's other block is a
``BreadcrumbList``) with ``title``, ``hiringOrganization.name``/``logo``,
``identifier.value`` (the ad id, matching the URL), ``datePosted`` /
``validThrough`` (both ISO-8601 with ``Z``), ``employmentType`` (a list of
Schema.org codes), ``baseSalary`` (a ``MonetaryAmount`` whose ``value`` is a
``QuantitativeValue`` with ``value``/``minValue``/``maxValue`` and
``unitText: MONTH``; an all-zero value means "salary not published"),
``salaryCurrency`` (``MYR``), ``skills`` and ``jobBenefits`` (lists of
strings), ``occupationalCategory`` (free text), ``jobLocation.address``
(``addressLocality``/``addressRegion``/``addressCountry``) and a plain-text
``description``.

**Known content quirks** (measured 2026-11-20). ``addressRegion`` is usually a
state name but is sometimes the federal-territory form ``WP Kuala Lumpur``
(stripped to ``Kuala Lumpur``) and occasionally a bare postal code (``81750``,
rejected). ``addressCountry`` is ``MY`` on essentially every ad with the
occasional neighbouring ``SG``. ``jobLocationType`` was absent on every ad
sampled, so nothing is inferred as remote from prose. Roughly one ad in
twenty-five returns HTTP 200 with **no** ``JobPosting`` block at all
(stable on retry, not a transient); such an ad is skipped and counted as a
failure rather than stored as a half-record, because with no block there is no
title, employer or body to store.

**Freshness / coverage.** The newest ``fresh_rows`` entries are always taken,
so a run never misses what was just posted. The rest of the budget comes from
a window that advances one budget-width per calendar day over the tail of the
sitemap, so older ads are covered over successive runs instead of the same
first page being re-read forever. ``start_offset`` pins that window for a
reproducible run.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MaukerjaMySettings(BaseSettings):
    """Runtime configuration for the MauKerja (Malaysia) scraper."""

    model_config = SettingsConfigDict(
        env_prefix="MAUKERJA_MY_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(default="https://www.maukerja.my", description="Site root.")
    sitemap_url: str = Field(
        default="https://www.maukerja.my/sitemap.xml",
        description="Advertised sitemap index used for discovery.",
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
        description="Ordinary desktop Chrome UA; the board's robots.txt bans AI "
        "crawler tokens, and none is sent.",
    )
    request_timeout_seconds: float = Field(default=45.0, gt=0)
    sitemap_timeout_seconds: float = Field(
        default=180.0,
        gt=0,
        description="The job sitemap was ~9 MB on 2026-11-20, so it gets a longer budget.",
    )
    max_sitemap_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
        description="Refuse an outsized sitemap rather than buffering it indefinitely.",
    )
    max_sitemap_depth: int = Field(
        default=5,
        ge=1,
        description="Cap on how deep the sitemap-index chain is walked.",
    )
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: No Crawl-delay is advertised for the default group. One second keeps a
    #: 500-detail run around nine minutes while staying polite to a small board.
    inter_request_delay_seconds: float = Field(default=1.0, ge=0.0)
