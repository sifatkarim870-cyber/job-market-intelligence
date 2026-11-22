"""Configuration for the National Employment Agency (Cambodia) scraper.

The National Employment Agency (``www.nea.gov.kh``) is Cambodia's state
employment portal, run by the Ministry of Labour. Its vacancy board is
server-rendered ASP-style markup: the search page posts a form to
``/vacancy/dtlSearch.do`` and each result row calls
``fnVacancyViewNew('<32 hex>')``, which opens
``/vacancy/view.do?condSeq=<32 hex>``. No key, no login, no proxy, no browser
automation, and TLS verification stays on.

Measured on 2026-11-22
----------------------

* The bare root ``/`` answers a Cloudflare JS-challenge shell (~1.7 KB) to a
  non-browser client, but the *content* paths do not: ``/index.do``,
  ``/vacancy/dtlSearch.do`` and ``/vacancy/view.do`` are ordinary
  server-rendered HTML over ``curl_cffi`` with ``impersonate="chrome"``. The
  client never requests the bare root, so no challenge is ever handled.
* The board reported ``654`` vacancies on 2026-11-22, ten per search page
  (~66 pages). Pagination is a POST of ``condDiv=SEARCH``,
  ``condText=""`` and ``currentPageNo=N``; pages 1/2/3 returned ten distinct
  ``condSeq`` values each.
* Detail pages are ~60-72 KB and carry the title in ``#vacancyTitle``, the
  employer in the first ``.tit_box span.tit``, a summary block of
  ``.cont > strong.tit`` + ``span.con`` pairs, and labelled sections in
  ``.form_wrap`` (``.form_title h3`` + ``.view_form strong.title`` +
  ``p.cont_box``/``div.cont_box``).
* Salaries are quoted in **US dollars per month** (Cambodia's dollarised
  labour market): ``ប្រាក់ឈ្នួលគោល`` reads ``$210 ~ $250 (ខែ)`` and the
  summary ``ប្រាក់បៀវត្ស`` reads ``ខែ $210~$250``.
* The recruitment window ``រយៈពេលជ្រើសរើស`` reads
  ``20/11/2026 ~ 13/02/2027``; its start is stored as the posting date and
  its end as the closing date. A literal ``00/00/0000`` start is discarded.
* A Khmer-language board: titles, employers and field values are usually
  Khmer, with some English titles. The parser therefore keys on the board's
  own Khmer labels rather than on English text.

robots.txt
----------

``https://www.nea.gov.kh/robots.txt`` (HTTP 200) is the Cloudflare-managed
generic ``User-agent: *`` group with ``Allow: /`` (plus a ``Content-Signal``
line: ``search=yes,ai-train=no,use=reference``). The later training-crawler
groups (``GPTBot``, ``ClaudeBot``, ...) do not name this scraper's ordinary
browser User-Agent, and none of them restricts the vacancy paths read here.
No query string is appended beyond the board's own ``condSeq`` detail
parameter, and no account, resume or employer path is ever requested.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class NeaGovKhSettings(BaseSettings):
    """Runtime knobs for the NEA Cambodia scraper.

    Environment prefix: ``NEA_GOV_KH_``.
    """

    model_config = SettingsConfigDict(
        env_prefix="NEA_GOV_KH_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(
        default="https://www.nea.gov.kh",
        description="Public site root (the content paths, not the challenged bare root).",
    )
    search_path: str = Field(
        default="/vacancy/dtlSearch.do",
        description="Server-rendered vacancy search endpoint (POST).",
    )
    detail_path: str = Field(
        default="/vacancy/view.do",
        description="Server-rendered vacancy detail endpoint (GET ?condSeq=...).",
    )

    pages_per_run: int = Field(
        default=6,
        ge=1,
        description=(
            "Search pages walked per run. Ten vacancies per page, so six pages "
            "cover the 60-ad budget without reading the whole ~66-page board."
        ),
    )
    max_jobs_per_run: int = Field(
        default=60,
        ge=1,
        description="Hard ceiling on detail pages fetched (and rows persisted) in one run.",
    )
    max_detail_attempts: int = Field(
        default=80,
        ge=1,
        description=(
            "Ceiling on detail pages requested, including withdrawn/expired ones, "
            "so a run of dead links cannot stall the pipeline."
        ),
    )

    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        description="Browser-shaped User-Agent.",
    )
    impersonate: str = Field(
        default="chrome",
        description="curl_cffi browser impersonation profile (empty string disables it).",
    )

    request_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        description=(
            "Per-request timeout. The NEA origin is slow (Cloudflare's edge "
            "timer measured ~20 s on a cold request), so this is generous."
        ),
    )
    max_retry_attempts: int = Field(default=3, ge=1, description="Attempts per request.")
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=30.0, ge=0.0)

    inter_request_delay_seconds: float = Field(
        default=1.0,
        ge=0.0,
        description="Polite gap between requests; the board publishes no Crawl-delay.",
    )

    fetch_details: bool = Field(
        default=True,
        description=(
            "Fetch each detail page. A run is useless without it; the switch "
            "keeps offline tests honest."
        ),
    )
