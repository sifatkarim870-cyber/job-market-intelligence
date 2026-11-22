"""Configuration for the Kariyer.net scraper -- Turkiye.

Kariyer.net is Turkiye's largest generalist job board. Its ``www`` marketing
HTML is behind HUMAN/PerimeterX (``PXqzR3QUY9``), but the board's own SPA
talks to two *public* JSON gateways that are **not** behind that
interstitial and need no key, no login and no proxy:

* search: ``POST https://candidatewebapigw.kariyer.net/jb/api/jobs/search``
* detail: ``GET  https://api-web.kariyer.net/job?jobId=<id>`` (mirrored by
  ``https://candidatesearchapigateway.kariyer.net/job?jobId=<id>``)

Both host names are published verbatim in the site's own JavaScript bundle
(``VUE_APP_API_DOMAIN`` / ``VUE_APP_API_V4_DOMAIN`` / ``VUE_APP_API_DOMAIN_V1``),
so they are the board's documented client API rather than a reverse-engineered
private endpoint. The bundle's own job-detail call targets the ``...V4`` host
with an ``Api-Version: 1.1`` header; that host is PX-fronted and *rejects* the
``1.1`` header from a cookieless client (403), whereas the ``api-web`` mirror
serves the identical document with no ``Api-Version`` header at all -- so the
scraper reads the mirror and never sends ``Api-Version``.

**robots.txt** (``/robots.txt``, HTTP 200). The generic ``User-agent: *``
group disallows ``/filtre*``, ``*?v=*``, ``*?ckw*``, ``*?copilot*`` and the
candidate/account paths, and **allows** the two surfaces this scraper reads:
``/is-ilanlari`` (the listing) and ``/is-ilani/`` (the ad detail pages). The
scraper does not request any disallowed path; it requests the gateways, which
serve the same public ad content the allowed pages render, and it links back
to the allowed ``/is-ilani/<slug>-<id>`` pages.

Measured on 2026-11-22:

* the search endpoint caps a requested ``pageSize`` at ~53 items regardless of
  the value sent, and page windows overlap and rotate -- so pagination is
  **fuzzy** and de-duplicating by ``jobId`` is mandatory, not an optimisation.
* the detail endpoint serves a rich JSON document
  (``data.jobGeneralInformation`` / ``jobPositionInformation`` /
  ``jobCandidateCriteria`` / ``jobCompanyInformation``); ``data.jobSalaryBudget``
  is ``null`` on every Turkish posting sampled, so real salary figures are
  almost never published and rows are stored salary-undisclosed in TRY.
* the detail endpoint rejects a browser-shaped request that omits the
  ``Origin``/``Referer`` pair (HTTP 403) and, more importantly, rejects plain
  ``requests`` entirely on its TLS fingerprint; it answers a real Chrome
  handshake. That is why this client speaks through ``curl_cffi`` for both
  calls (the same fix JobsNepal and Job.am use for their Cloudflare fronts).
  It must NOT send ``Api-Version``: adding that header turns a 200 into a 403.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KariyerNetSettings(BaseSettings):
    """Runtime knobs for the Kariyer.net scraper (env prefix ``KARIYER_NET_``)."""

    model_config = SettingsConfigDict(
        env_prefix="KARIYER_NET_",
        case_sensitive=False,
        extra="ignore",
    )

    #: Public SPA gateway base (the ``VUE_APP_API_DOMAIN`` the bundle publishes).
    search_base_url: str = Field(
        default="https://candidatewebapigw.kariyer.net/jb/api",
        description="Candidate web API gateway base.",
    )
    search_path: str = Field(default="/jobs/search", description="Job search endpoint path.")

    #: Public SPA gateway base. The bundle's ``VUE_APP_API_V4_DOMAIN``
    #: (``candidatesearchapigateway.kariyer.net``) serves the same ``/job``
    #: document, but that host is behind HUMAN/PerimeterX and intermittently
    #: answers 403 (PX body) to a client without a valid visitor cookie --
    #: measured 14/15 over one run on 2026-11-22. ``api-web.kariyer.net`` (the
    #: bundle's ``VUE_APP_API_DOMAIN_V1``) mirrors ``/job?jobId=<id>`` byte-for
    #: -byte and answered 15/15, so it is the primary; ``detail_fallback_base_url``
    #: below keeps the PX host as a secondary for when the mirror is down.
    detail_base_url: str = Field(
        default="https://api-web.kariyer.net",
        description="Public job-detail gateway base (non-PX mirror).",
    )
    detail_path: str = Field(default="/job", description="Job detail endpoint path.")

    #: Secondary detail host, tried only when the primary fails. This is the
    #: SPA's own ``VUE_APP_API_V4_DOMAIN``; it serves the identical document but
    #: is PX-fronted, so it is a fallback rather than the default.
    detail_fallback_base_url: str = Field(
        default="https://candidatesearchapigateway.kariyer.net",
        description="Secondary (PX-fronted) job-detail gateway base.",
    )

    #: Used only to build the public ``/is-ilani/<slug>-<id>`` URL stored as
    #: ``original_url``; the scraper never fetches HTML from this host.
    site_base_url: str = Field(
        default="https://www.kariyer.net",
        description="Public site root, for constructing the canonical ad URL.",
    )

    page_size: int = Field(
        default=50,
        ge=1,
        le=50,
        description=(
            "Rows requested per search page. The API caps the response at ~53 "
            "whichever value is sent (50 and 100 both returned 53 on 2026-11-22), "
            "so the ceiling is 50 to keep the short-page signal honest."
        ),
    )
    max_pages_per_run: int = Field(
        default=3,
        ge=1,
        description=(
            "Search windows walked per run. Each is one request. Because the "
            "windows overlap and rotate, more pages mostly re-serve ids already "
            "collected; three is comfortably more than the per-run detail budget."
        ),
    )
    max_jobs_per_run: int = Field(
        default=60,
        ge=1,
        description="Hard ceiling on postings fetched (detail calls) and persisted in one run.",
    )

    request_timeout_seconds: float = Field(default=30.0, gt=0, description="Per-request timeout.")
    max_retry_attempts: int = Field(default=3, ge=1, description="Attempts per request.")
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: One request per detail ad. A one-second gap is polite and keeps a
    #: 60-detail run near a minute of wall time with the retry ceiling intact.
    inter_request_delay_seconds: float = Field(default=1.0, ge=0.0)

    fetch_details: bool = Field(
        default=True,
        description=(
            "Fetch each ad's detail document for its description and metadata. "
            "A run is useless without it; the switch keeps offline tests honest."
        ),
    )

    #: curl_cffi browser impersonation profile. The detail gateway answers a
    #: real Chrome TLS/HTTP2 handshake and rejects plain ``requests`` outright.
    impersonate: str = Field(
        default="chrome",
        description=(
            "curl_cffi browser impersonation profile (e.g. ``chrome``, ``edge``, "
            "``safari``). Empty string disables it."
        ),
    )
