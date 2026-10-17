"""Configuration for the Vagas.com.br scraper (Brazil).

Measured on the live site on 2026-10-18 rather than assumed:

  * **Discovery** is ``/vagas-de-emprego/?page=N``. Exactly **40** posting links
    per page, and the pager is real: ``?page=2`` returned **40 new ids with zero
    overlap** against page 1. ``?pagina=2`` also paginates; ``?p=2`` serves a
    30 KB page with **0** postings, so it is not the parameter.

  * robots.txt is real ``text/plain`` (689 bytes). The ``User-Agent: *`` group
    disallows ``/auth/``, ``/move_to``, ``/servicos/``, ``/v1/``, ``/api/``,
    ``/social/``, ``/users/``, ``/token/``, ``/vagas/pesquisas``,
    ``/suporte``, ``/mapa-de-carreiras/cargo/`` and ``/suporte-flix``. The
    listing and ``/vagas/v<id>/<slug>`` are **not** disallowed, and a
    ``Sitemap:`` is nominated.

  * Detail pages carry a schema.org ``JobPosting`` in a ``<script
    type="application/ld+json">`` block. The block is **malformed on some
    pages** (raw control characters), so the parser attempts a plain
    ``json.loads`` first and falls back to ``json.loads(block, strict=False)``.

Three traps in the payload, each measured:

  1. ``addressCountry`` is the **name** ``"Brasil"``, not an ISO code. Every
     other source in this project that carries a country gives either ``PT`` or
     ``ZA``; treating this as an ISO code silently resolves nothing.
  2. ``identifier`` is a ``PropertyValue`` whose ``value`` is an **int**
     (``2831966``), not a string. ``str()`` on it is mandatory.
  3. ``baseSalary`` uses ``value.unitText`` + ``value.minValue``/``maxValue``
     **flat** -- a sixth distinct layout in this codebase. It is also present
     on only some postings: 1 of 3 measured carried one.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VagasComBrSettings(BaseSettings):
    """Configuration for the Vagas.com.br Brazilian job board."""

    model_config = SettingsConfigDict(env_prefix="VAGAS_COM_BR_", extra="ignore")

    base_url: str = Field(default="https://www.vagas.com.br", description="Site root.")
    listing_path: str = Field(
        default="/vagas-de-emprego/", description="Server-rendered listing page."
    )

    max_pages: int = Field(
        default=6,
        ge=1,
        le=200,
        description=(
            "Listing pages to walk. 40 postings per page, so 6 pages is ~240. "
            "Measured to paginate cleanly with 40 new ids per page."
        ),
    )

    max_jobs_per_run: int = Field(
        default=60,
        ge=1,
        description=(
            "Cap on postings persisted in one run (VAGAS_COM_BR_MAX_JOBS_PER_RUN). "
            "Deliberately well below the 150 used elsewhere: the site throttles "
            "hard, so a smaller batch keeps a run inside the CI timeout instead "
            "of spending the whole window on HTTP 429 backoff."
        ),
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA. No key or registration is involved.",
    )

    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: **Rate limited, measured.** Vagas.com.br served 429 to 30 of 45 detail
    #: fetches at 1.0s on 2026-10-18 -- the first ~15 succeeded and everything
    #: after was throttled. 3.5s clears it in practice; the Mustakbil scraper
    #: settled on 4.0s for the same reason, and the default is pinned by test
    #: because "slow enough" is the only setting this source really has.
    inter_request_delay_seconds: float = Field(default=3.5, ge=0.0)

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
            "The pager is real, so this guards against it regressing to static."
        ),
    )

    min_links_per_page: int = Field(
        default=5,
        ge=1,
        description=(
            "A page with fewer links than this is treated as the tail -- its "
            "links are still collected first. Pages carry 40."
        ),
    )
