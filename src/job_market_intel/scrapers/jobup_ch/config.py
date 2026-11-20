"""Configuration for the jobup.ch scraper -- Switzerland (French-speaking).

jobup.ch is JobCloud AG's French-Swiss brand (the same catalogue family as
jobs.ch, but a distinct board with its own inventory). It needs no key, no
registration and no proxy, and its advertised sitemaps are the whole discovery
surface. The facts below were measured from the live site on 2026-11-20.

**robots.txt** (``/robots.txt``, HTTP 200, 2,217 bytes) advertises::

    Sitemap: https://www.jobup.ch/sitemaps/jobup/fr/sitemap.xml
    Sitemap: https://www.jobup.ch/sitemaps/jobup/en/sitemap.xml

For ``User-agent: *`` it disallows ``/api/``, ``/api_proxy/``, ``/external/``,
all ``/de|en|fr/application*`` and login/register paths, ``/fe/ktunnel/``,
``/masks/``, ``/javascript/``, ``/*?*feat=`` and ``/*.map$``. None of those is
touched: discovery reads the advertised English sitemap index and the only
content requests are ``/en/jobs/detail/<uuid>/`` ad pages, which no rule
covers.

**Discovery** is the advertised sitemap index, measured 2026-11-20::

    /sitemaps/jobup/en/sitemap.xml        sitemapindex, 20 children
      -> .../job/sitemap.job-en.xml.gz    <urlset>, 30,590 job URLs, gzip

The index carries category, company, region and search sitemaps too; the walk
follows only children under the ``/job/`` path, so a future paginated
``sitemap.job-en_N.xml.gz`` is picked up automatically while every other
family is skipped. The English and French job sitemaps hold the same UUIDs
(30,590 vs 30,589 on 2026-11-20); the English one is used, so a job is not
stored twice.

**Content** is one request per ad. Every ``/en/jobs/detail/<uuid>/`` page
carries a Schema.org ``JobPosting`` JSON-LD block (the page's other block is a
``BreadcrumbList``). The block was measured on live pages on 2026-11-20 and
has these shapes:

* ``title``, ``description`` (HTML), ``datePosted`` (ISO-8601 with an offset).
* ``hiringOrganization`` is ``{name, logo, sameAs}``; ``logo`` is a string.
* ``jobLocation.address`` is ``{addressLocality, addressRegion,
  addressCountry}``. ``addressCountry`` was ``CH`` on 100% of ads sampled;
  ``addressLocality`` and ``addressRegion`` are often absent and are
  inconsistent when present (a town in the region slot, a postcode in
  parentheses, even an internal ``EMEA > CHE > ...`` path).
* ``employmentType`` is **either** a list of Schema.org codes
  (``["FULL_TIME"]``) **or** a prose string (``"Permanent position"``,
  ``"Temporary"``, ``"Apprenticeship"``), so both shapes are handled.
* ``baseSalary`` is a ``MonetaryAmount`` (``currency: CHF``) whose ``value`` is
  a ``QuantitativeValue`` with ``minValue``/``maxValue`` and
  ``unitText: YEAR`` when a salary is published; roughly a third of the
  sampled ads carried a salary and about half of those had an empty
  ``QuantitativeValue`` (published but with no numbers, stored as undisclosed).
* ``identifier`` is a ``PropertyValue`` whose ``value`` is the ad UUID.
* ``applicantLocationRequirements`` is ``{"@type": "Country", "name":
  "Switzerland"}`` -- an eligibility statement, **not** a remote signal, so it
  never sets a remote type. Only an explicit ``jobLocationType: TELECOMMUTE``
  does.

**Freshness / coverage.** The newest ``fresh_rows`` entries are always taken,
so a run never misses what was just posted. The rest of the budget comes from
a window that advances one budget-width per calendar day over the tail, so
older ads are covered over successive runs instead of the same slice being
re-read forever. ``start_offset`` pins that window for a reproducible run.

**Note on the sibling board.** ``jobs_ch`` (jobs.ch) is the same company's
German-Swiss brand. They share a UUID space but not (fully) their inventory:
on 2026-11-20 a 15-ad sample of jobup.ch UUIDs resolved on neither the
``en``, ``fr`` nor ``de`` jobs.ch detail path for 8 of 15, so jobup.ch carries
meaningfully distinct postings and is not a duplicate of ``jobs_ch``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobupChSettings(BaseSettings):
    """Runtime configuration for the jobup.ch (Switzerland) scraper."""

    model_config = SettingsConfigDict(
        env_prefix="JOBUP_CH_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(default="https://www.jobup.ch", description="Site root.")
    sitemap_url: str = Field(
        default="https://www.jobup.ch/sitemaps/jobup/en/sitemap.xml",
        description="Advertised sitemap index used for discovery (English).",
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
        description="Ordinary desktop Chrome UA; no bot token is sent.",
    )
    request_timeout_seconds: float = Field(default=45.0, gt=0)
    sitemap_timeout_seconds: float = Field(
        default=180.0,
        gt=0,
        description="The gzipped job sitemap was ~0.8 MB (5.9 MB inflated) on "
        "2026-11-20, so it gets a longer budget.",
    )
    max_sitemap_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
        description="Refuse an outsized sitemap (raw or inflated) rather than "
        "buffering it indefinitely.",
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
    #: 500-detail run polite while still finishing inside the CI timeout.
    inter_request_delay_seconds: float = Field(default=1.0, ge=0.0)
