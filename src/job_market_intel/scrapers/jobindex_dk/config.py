"""Configuration for the Jobindex (jobindex.dk) scraper.

Measured on the live site on 2026-11-20 rather than assumed:

  * **robots.txt** (HTTP 200) has a generic ``User-agent: *`` group with **no**
    ``Crawl-delay``. It disallows the paged/sorted/filtered search URLs
    (``/jobsoegning*page=``, ``*sort=``, ``*jobage=``, ``*archive=``,
    ``*subid=``, ``*supid=``, ``*companyid=``, ``*radius=``, ``*flag=``,
    ``*geoareaid=``, ``/jobsoegning?*&*&``, ``/jobsoegning/*?*&``,
    ``/jobsoegning/kort``, ``/jobsoegning/uopfordret``,
    ``/jobsoegning/analyse``), every ``/c?`` redirect link, and
    ``/jobannonce/korrektur/`` / ``/jobannonce/embed/``. The surfaces this
    scraper uses -- ``/jobsoegning`` and ``/jobsoegning/<area>`` listing
    pages, ``/sitemap/area.gz``, ``/vis-job/<tid>`` and
    ``/jobannonce/<tid>/<slug>`` -- are allowed. A short polite gap is kept
    anyway (no Crawl-delay is a floor, not an invitation).

  * **Discovery** is the board's own advertised sitemap
    ``https://www.jobindex.dk/sitemap.gz`` (a ``<sitemapindex>``) whose
    ``area.gz`` child is a ``<urlset>`` of 759 allowed
    ``/jobsoegning/<slug>`` area pages. There is no job-ad sitemap:
    ``googleforjobs.gz`` is an **empty** ``<urlset>`` (0 ``<loc>``, even when
    fetched as Googlebot), and ``company.gz``/``salaryindex.gz``/``content.gz``
    hold company profiles, salary pages and articles, not ads.

  * Each listing page embeds a large ``var Stash = {...}`` JSON object. Under
    ``["jobsearch/result_app/list"]["storeData"]["searchResponse"]`` it carries
    ``hitcount``, ``total_pages``, ``max_page`` (50), ``page_size`` (20) and a
    ``results`` array of 20 ad objects with ``tid``, ``headline``,
    ``companytext``, ``firstdate``, ``lastdate``, ``apply_deadline``,
    ``salary``, ``home_workplace``, ``area``, ``addresses``, ``listlogo_url``
    and the rendered snippet in ``html``. The board held **18,829** active ads
    over a reported 942 pages on 2026-11-20, but ``page=`` is
    robots-DISALLOWED, so pages are never walked; instead the 759 allowed area
    pages are sampled in a rotating window and deduped by ``tid``. A sample of
    20 area pages yielded 263 rows and 198 unique ads, so a full area pass
    covers several thousand distinct ads and successive runs cover more.

  * **Content** is one request per ad where the listing snippet exposes the
    canonical ``/jobannonce/<tid>/<slug>`` URL, and one request to
    ``/vis-job/<tid>`` otherwise. ``/jobannonce/<tid>/<slug>`` carries the full
    body in ``section.jobtext-jobad__body``; the slug is required (a wrong or
    missing slug returns HTTP 200 with no body), so the slug is taken from the
    listing snippet or from the ``<link rel="canonical">`` on the ``vis-job``
    page. Measured on 60 sampled ads: 15 (25%) have a full body (1,708-8,149
    chars, median 3,310) and 45 (75%) are employer-paid ads that only publish a
    ~530-695 char teaser on Jobindex and link out to the employer, whose full
    text is therefore **not on this board**. A teaser is stored as the
    description and flagged in ``raw_payload``; no external employer page is
    fetched.

  * **Salary** was ``null`` on all 116 sampled listing rows, and the ad pages
    carry no salary field, so no amount is invented. Rows state DKK / monthly.

  * **Employment type** and **remote work** are published only on full-body ad
    pages, in the "Virksomheden tilbyder" / "The company offers" sidebar card:
    ``Ansættelsestype`` (Fastansættelse, Permanent, Freelance, Studiejob,
    Fleksjob ...), ``Hjemmearbejde`` (100 % hjemmearbejde, 100% remote,
    Tilbydes ikke, Ikke oplyst ...) and ``Ugentlig arbejdstid`` (Fuldtid,
    Deltid (12-37 timer) ...). Teaser-only ads publish none of this, so their
    type is ``None`` unless the listing's ``home_workplace`` flag is set.

  * No key, no registration, no proxy, no browser.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobIndexSettings(BaseSettings):
    """Runtime configuration for the Jobindex scraper."""

    model_config = SettingsConfigDict(
        env_prefix="JOBINDEX_DK_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(default="https://www.jobindex.dk", description="Site root.")
    listing_url: str = Field(
        default="https://www.jobindex.dk/jobsoegning",
        description="Newest-first search page; takes no query string.",
    )
    sitemap_url: str = Field(
        default="https://www.jobindex.dk/sitemap/area.gz",
        description="Advertised area-page <urlset>; the only ad-bearing sitemap child.",
    )

    max_area_pages: int = Field(
        default=60,
        ge=1,
        le=759,
        description="Area listing pages walked per run (the sitemap has 759).",
    )
    max_jobs_per_run: int = Field(
        default=500,
        ge=1,
        description="Cap on ad pages fetched and postings persisted in one run.",
    )

    #: The newest rows are always taken, so a run never misses what was just
    #: posted. The rest of the budget comes from an area-page/row window that
    #: moves with the calendar (see ``start_offset``), so the long tail is
    #: covered over time instead of the same first page being re-read forever.
    fresh_rows: int = Field(
        default=80,
        ge=0,
        description="Newest listing rows always sampled, ahead of the rotating window.",
    )
    #: ``None`` = derive the window start from today's date, advancing one
    #: window-width per day. Pinning this makes a run reproducible (tests and
    #: manual runs use it); CI leaves it unset.
    start_offset: int | None = Field(
        default=None,
        ge=0,
        description="Override for the rotating area/row window start.",
    )

    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        description="Browser user agent; the site serves plain HTML to it.",
    )
    request_timeout: float = Field(default=30.0, gt=0)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=15.0, ge=0.0)

    #: robots.txt sets no Crawl-delay for ``*``. This is a courtesy gap between
    #: any two requests, listing or ad page, not a claim about a published limit.
    rate_limit_delay: float = Field(default=0.25, ge=0.0)
