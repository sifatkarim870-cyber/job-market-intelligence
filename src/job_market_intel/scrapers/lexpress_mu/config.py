"""Configuration for the L'Express Petites Annonces (Mauritius) jobs scraper.

Measured on the live site on 2026-11-21 rather than assumed:

  * **Discovery** is the classifieds jobs category ``/c/emplois`` on the
    sister host ``lexpress-petites-annonces.mu``. The news host
    ``lexpress.mu`` only links to it.
  * The category is server-rendered and paginates with ``?page={n}``;
    page 1 is the bare path. Each page carries ~12 ads and the whole
    category held 126+ ads across 11+ live pages when measured.
  * **Detail pages carry no schema.org JSON-LD.** Every field is Tailwind
    markup::

        <h1 class="text-2xl font-bold w-[65%]">Pool Attendant - Azuri (Roches Noires)</h1>
        <p class="text-xs lg:text-md font-bold">Ref: 20261116-1794825510</p>
        <p class="text-sm text-gray-500">Emplois  &gt; Full-Time</p>
        <p class="mt-1 text-xs text-gray-500">16 novembre 2026</p>
        <p class="text-lg">&lt;body with newlines and a Cloudflare-obfuscated email&gt;</p>
        <p class="text-sm text-gray-500">Localisation: Roches Noires</p>

  * The ad URL is ``/annonce/<YYYYMMDD>-<digits>`` and that whole token is
    the stable ``source_job_id``.
  * **Dates are French long form** (``16 novembre 2026``); ``_parse_date``
    in the shared framework cannot read French month names.
  * There is **no structured employer and no structured salary**. The
    employer is best-effort (the ad's Google-Maps query, then a body
    heuristic) and the salary, when stated, is prose in the body
    (``Salary Package: MUR 27,000 - MUR 35,000 per month.``).

  * ``robots.txt`` on both hosts is a generic ``*`` group with an empty
    ``Disallow`` (allow-all).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LexpressMuSettings(BaseSettings):
    """Configuration for L'Express Petites Annonces (Mauritius) jobs."""

    model_config = SettingsConfigDict(env_prefix="LEXPRESS_MU_", extra="ignore")

    base_url: str = Field(
        default="https://lexpress-petites-annonces.mu", description="Classifieds host root."
    )
    listing_path: str = Field(default="/c/emplois", description="Server-rendered jobs category.")

    max_pages: int = Field(
        default=12,
        ge=1,
        le=200,
        description="Listing pages to walk. The category held 11+ live pages.",
    )
    max_jobs_per_run: int = Field(
        default=120, ge=1, description="Cap on postings persisted in one run."
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)", description="Identifying UA."
    )
    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Detail pages are ~18 KB and the listing ~54 KB. 0.5s keeps a full
    #: 120-ad run under a couple of minutes while staying polite.
    inter_request_delay_seconds: float = Field(default=0.5, ge=0.0)

    fetch_description: bool = Field(
        default=True, description="Fetch each detail page for the body and metadata."
    )
    stop_after_repeated_empty_pages: int = Field(default=2, ge=1)
    min_links_per_page: int = Field(
        default=6, ge=1, description="Tail threshold. Pages carry ~12 ads."
    )
