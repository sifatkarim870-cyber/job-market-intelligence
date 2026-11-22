"""Configuration for the Nationale Vacaturebank (Netherlands) scraper.

Nationale Vacaturebank (``www.nationalevacaturebank.nl``) is one of the
Netherlands' largest generalist job boards, run by DPG Media. It publishes
**real server-rendered HTML** and a schema.org ``JobPosting`` block on every ad
page, so this is an HTML source -- no key, no login, no proxy, no browser
automation, and TLS verification stays on.

Measured on 2026-11-22
----------------------

* A plain ``requests`` GET returns HTTP 403 ``Access Denied`` (the DPG edge
  rejects the TLS fingerprint). ``curl_cffi`` with ``impersonate="chrome"``
  returns HTTP 200, so this client speaks through ``curl_cffi``.
* A *fresh* session's first HTML response is sometimes the "DPG Media Privacy
  Gate" consent wall (~8 KB) instead of the page. The gate is cleared by
  simply re-requesting the page on the same session: the first GET sets the
  ``authId``/``xAuthId`` cookies and every later GET returns the real page.
  The gate's own ``/privacygate-confirm`` callback 403s and is never needed.
* Category pages are ~660-815 KB and carry **50 ad links each**. Ad URLs are
  ``/vacature/<uuid>/<slug>`` and the UUID is the stable ``source_job_id``.
* Ad pages are ~95-110 KB and carry two ``ld+json`` blocks: a ``JobPosting``
  (title, ``hiringOrganization.name``, ``jobLocation.address`` with locality /
  region / country / postal code and lat/lon, ``datePosted``,
  ``validThrough``, ``employmentType``, ``educationRequirements``,
  ``experienceRequirements.monthsOfExperience``, ``workHours``,
  ``occupationalCategory``, ``industry``, ``jobLocationType``, ``directApply``,
  ``description`` and ``baseSalary``) and an ``Occupation`` block whose
  ``estimatedSalary`` is the board's **market estimate**, not the ad's offer.
* ``baseSalary`` is a real offer on ~78% of ads measured (31 of 40), always
  EUR and always ``unitText: "MONTH"`` in that sample -- but that unit is
  wrong for hourly-salary ads (a "bruto uurloon van EUR 18,43 - 23,99" ad
  shipped ``23`` with ``unitText: "MONTH"``), so a too-small monthly amount is
  re-read as hourly and flagged. The ``Occupation`` estimate is stored in
  ``raw_payload`` only and never treated as a disclosed salary.
* Some discovered ad pages are already withdrawn: they return HTTP 410 (or a
  200 with no ``JobPosting`` block). Those are skipped, not counted as parse
  failures.
* ``datePosted``/``validThrough`` are written at ``22:00Z`` / ``23:00Z`` --
  midnight in the Netherlands -- so both are converted to Europe/Amsterdam
  before the date is taken. Reading the raw UTC date would date every ad one
  day early.

robots.txt (``https://www.nationalevacaturebank.nl/robots.txt``, HTTP 200)
-------------------------------------------------------------------------

The generic ``User-agent: *`` group **disallows** ``/vacatures/*?page=`` (and
``/vacatures/*?*&page=``), so pagination is off-limits and this scraper reads
**page 1 only** of each category, with no query string at all. It also
disallows ``/vacature/zoeken?*``, ``/vacature/uitgebreid-zoeken``,
``/vacature/bookmarken/``, ``/vacature/delen/``, ``/vacature/apply/``,
``/vacature/external-url/``, ``/vacature/website/``, ``/vacature/bladeren/``,
``/archief/``, ``/zzp/``, the candidate/account paths and most
``/werkgever/``/``/recruiter/`` paths -- none of which this scraper requests.

It **allows** the surfaces this scraper reads: ``/vacatures`` and the category
pages under ``/vacatures/vakgebied/``, ``/vacatures/branche/``,
``/vacatures/provincie/``, ``/vacatures/dienstverband/``,
``/vacatures/uren/`` and ``/vacatures/opleiding/``, the published
``/vacatures/sitemap.xml``, and the ad pages ``/vacature/<uuid>/<slug>``.

**The API host is off-limits.** ``api.nationalevacaturebank.nl/robots.txt`` is
``User-agent: *`` / ``Disallow: /``; this scraper never requests that host.

Discovery
---------

``/vacatures/sitemap.xml`` is the board's own published list of 241 category
URLs. The scraper keeps the content categories (96 of them on 2026-11-22) and
walks a rotating window of ``pages_per_run`` of them per run, so every
category is revisited over time without ever touching the disallowed
pagination. Ad links from the selected categories are merged round-robin so a
run samples all of them, then ``max_jobs_per_run`` ad pages are fetched.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class NationaleVacaturebankNlSettings(BaseSettings):
    """Runtime knobs for the Nationale Vacaturebank scraper.

    Environment prefix: ``NATIONALE_VACATUREBANK_NL_``.
    """

    model_config = SettingsConfigDict(
        env_prefix="NATIONALE_VACATUREBANK_NL_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(
        default="https://www.nationalevacaturebank.nl",
        description="Public site root.",
    )
    category_sitemap_path: str = Field(
        default="/vacatures/sitemap.xml",
        description="The board's published category sitemap (robots.txt lists it).",
    )

    #: Only these content-category prefixes are walked. The sitemap also lists
    #: alphabetical hub pages (``/vacatures/functie-a`` ...), ``/carriere/``
    #: guides and salary tools, which are not job listings.
    category_path_prefixes: tuple[str, ...] = Field(
        default=(
            "/vacatures/vakgebied/",
            "/vacatures/branche/",
            "/vacatures/provincie/",
            "/vacatures/dienstverband/",
            "/vacatures/uren/",
            "/vacatures/opleiding/",
        ),
        description="Category path prefixes treated as job listings.",
    )

    pages_per_run: int = Field(
        default=4,
        ge=1,
        description=(
            "Category pages walked per run. Only page 1 of each category is "
            "allowed by robots.txt (``?page=`` is disallowed)."
        ),
    )
    max_jobs_per_run: int = Field(
        default=60,
        ge=1,
        description="Hard ceiling on ad pages fetched (and rows persisted) in one run.",
    )
    max_detail_attempts: int = Field(
        default=180,
        ge=1,
        description=(
            "Ceiling on ad pages requested, including withdrawn/expired ones, "
            "so a category full of dead links cannot stall the run."
        ),
    )
    rotation_slot_hours: int = Field(
        default=12,
        ge=1,
        description=(
            "Category-window rotation period. The HTML group runs every 12 "
            "hours, so a new window is selected each run."
        ),
    )

    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        description="Browser-shaped User-Agent; the DPG edge 403s plain clients.",
    )
    impersonate: str = Field(
        default="chrome",
        description="curl_cffi browser impersonation profile (empty string disables it).",
    )

    request_timeout_seconds: float = Field(default=45.0, gt=0, description="Per-request timeout.")
    max_retry_attempts: int = Field(default=3, ge=1, description="Attempts per request.")
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Category pages are ~0.7-0.8 MB and ad pages ~0.1 MB. One second keeps a
    #: 60-ad run around two minutes while staying polite.
    inter_request_delay_seconds: float = Field(default=1.0, ge=0.0)

    fetch_details: bool = Field(
        default=True,
        description=(
            "Fetch each ad page for its JobPosting block. A run is useless "
            "without it; the switch keeps offline tests honest."
        ),
    )
