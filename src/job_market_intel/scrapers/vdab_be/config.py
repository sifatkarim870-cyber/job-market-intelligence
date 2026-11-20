"""Configuration for the VDAB (Flanders, Belgium, vdab.be) scraper.

Measured on the live service on 2026-11-21 rather than assumed.

**robots.txt** (HTTP 200) has a generic ``User-agent: *`` group with **no**
``Crawl-delay``. It disallows ``/vac/``, ``/vacatures/``, ``/api/vindeenjob/``,
``/include/vacature/`` and ``/*action=*``. The surfaces this scraper uses --
``/rest/vindeenjob/v4/vacatureLight/zoek`` and
``/rest/vindeenjob/v4/vacatures/<id>`` -- carry no matching rule (the prefix
rule ``/vacatures/`` does not match ``/vindeenjob/vacatures/...``), so both are
allowed. The disallowed ``/api/vindeenjob/`` base (used only for applications
and attachments) is never touched, and the Angular ad *pages* are never fetched
either: everything comes from the REST API. A short polite gap is kept anyway
(no Crawl-delay is a floor, not an invitation).

**Discovery** is the board's own search endpoint
``POST /rest/vindeenjob/v4/vacatureLight/zoek`` with body
``{"criteria": {...}, "pagina": N, "zoekmodus": "C2", "paginaGrootte": M}``.
``paginaGrootte`` up to 200 is accepted. The board reported ~212,800 active
vacancies on 2026-11-21. Results are requested with ``criteria.sorteerVeld =
"DATUM"`` so the first pages are the newest ads (without it the default order is
relevance, not date), then re-sorted locally by ``eerstePublicatieDatum`` desc
and numeric id desc so the window is deterministic even within a single day.

**Detail** is ``GET /rest/vindeenjob/v4/vacatures/<id>?preview=false``. The
payload carries a Schema.org ``jobPosting`` JSON *string* (title, markdown
description, ``hiringOrganization``, ``jobLocation``, ``employmentType``,
``datePosted``), plus a ``functie`` block (name, ``arbeidscircuit``,
``omschrijving.{html,markdown,plainText}``), a ``profiel`` block
(``dienstregeling.arbeidsDuur``, ``studies``, ``jobdomeinen``,
``beroepCompetenties``, ``talenKennis``, ``tewerkstellingsLocatie``,
``sollicitatieInfo``, ``voorgesteldeArbeidsovereenkomst.arbeidscontract``) and a
``leverancier`` block. See ``parser.py`` for the field mapping.

**The ``vej-key-monitor`` request header is required**: without it every request
returns HTTP 403 with an empty body, with it HTTP 200. It is *not* a credential
and *not* a secret -- it is a static public constant shipped verbatim in the
site's own JavaScript bundle (``webapps/vindeenjob/chunk-CpGZcmxc.js``, an
application-monitoring correlation id), visible to every browser that loads the
page. It is recorded here so the requests are shaped like the site's own, not to
authenticate. No account, API key, OAuth token, proxy or browser is used, and
TLS certificate verification is never disabled.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Static public correlation id the site's own front-end sends on every
#: ``/rest/vindeenjob/`` call. Present in ``chunk-CpGZcmxc.js``; not a secret.
DEFAULT_MONITOR_KEY = "b277002f-e1fa-4fc5-868a-fdab633c3851"


class VdabSettings(BaseSettings):
    """Runtime configuration for the VDAB scraper."""

    model_config = SettingsConfigDict(
        env_prefix="VDAB_BE_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(default="https://www.vdab.be", description="Site root.")
    search_url: str = Field(
        default="https://www.vdab.be/rest/vindeenjob/v4/vacatureLight/zoek",
        description="Search endpoint (robots-allowed).",
    )
    detail_url_template: str = Field(
        default="https://www.vdab.be/rest/vindeenjob/v4/vacatures/{job_id}",
        description="Detail endpoint template (robots-allowed).",
    )
    ad_url_template: str = Field(
        default="https://www.vdab.be/vindeenjob/vacatures/{job_id}",
        description="Canonical public ad URL stored as job_url/original_url.",
    )

    #: Static public front-end constant, not a credential -- see module docstring.
    monitor_key: str = Field(
        default=DEFAULT_MONITOR_KEY,
        description="Value for the required vej-key-monitor request header.",
    )
    search_mode: str = Field(default="C2", description="Vacancy search mode code.")
    online_sinds_code: str = Field(
        default="9000",
        description="onlineSinds filter; 9000 = 'Alle jobs' (all currently online).",
    )
    sort_field: str = Field(
        default="DATUM",
        description="sorteerVeld value; DATUM groups the newest ads on the first pages.",
    )
    page_size: int = Field(
        default=200,
        ge=1,
        le=200,
        description="Results per search page (the endpoint caps at 200).",
    )
    max_pages: int = Field(
        default=40,
        ge=1,
        description="Search pages walked per run (40 x 200 = 8,000 newest ads scanned).",
    )
    max_jobs_per_run: int = Field(
        default=500,
        ge=1,
        description="Cap on ad details fetched and postings persisted in one run.",
    )

    #: The newest rows are always taken, so a run never misses what was just
    #: posted. The rest of the budget comes from a window that advances one
    #: window-width per calendar day (see ``start_offset``), so the tail of the
    #: scanned set is covered over successive runs instead of the same first
    #: rows being re-read forever.
    fresh_rows: int = Field(
        default=200,
        ge=0,
        description="Newest ads always sampled, ahead of the rotating window.",
    )
    #: ``None`` = derive the window start from today's date, advancing one
    #: window-width per day. Pinning this makes a run reproducible (tests and
    #: manual runs use it); CI leaves it unset.
    start_offset: int | None = Field(
        default=None,
        ge=0,
        description="Override for the rotating window start.",
    )

    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        description="Browser user agent; the API serves plain JSON to it.",
    )
    request_timeout: float = Field(default=30.0, gt=0)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=15.0, ge=0.0)

    #: robots.txt sets no Crawl-delay for ``*``. This is a courtesy gap between
    #: any two requests, search page or detail, not a claim about a published
    #: limit.
    rate_limit_delay: float = Field(default=0.25, ge=0.0)
