"""JobMaster-specific configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or window change is a one-line ``.env``
edit (prefix ``JOBMASTER_``), not a code change.

JobMaster (``jobmaster.co.il`` — "ג'ובמאסטר", an Israeli job board)
facts confirmed live during the 2026-10-07 recon (probes r10–r18):

* **No API, no sitemap, no pagination without login.** Anonymous
  enriched access is HTML only: result cells are ``?headcatnum=<n>``
  × ``?jobtype=<n>`` filters on ``/jobs/`` (43 categories, 29
  job-type chips), each returning one page of 10 newest cards;
  *any* ``currPage`` (1, 2, POST, XHR, path-style) redirects to the
  account-login wall. A registered account could page (``register``
  flow demands an Israeli local phone via SMS — we do not register, so
  the client harvests what fits the anonymous window).
* **Detail pages are unrestricted**: ``/jobs/checknum.asp?key=<id>``
  renders the full record server-side. robots.txt allows everything
  on the ``www`` host except ``/api/`` — the client scrapes ``/jobs/``
  paths only.
* **Card parsing**: ``<article id="misra<ID>">`` per result, title
  under ``class="CardHeader"``, date as relative Hebrew text
  (``פורסם לפני 16 דקות`` = "posted 16 minutes ago"); the detail page
  repeats the same ``CardHeader``/``jobType``/``jobSalary``/
  ``jobLocation`` markup in ``article__jobHead`` + ``article__jobBody``.
* ``api.il.jobmaster.co.il`` serves open JSON dictionaries
  (``/api/check/groupBy/list/?q=…`` -> headcat/jobtype facet lists,
  incl. counters) used only to enumerate the filter-cell space.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobmasterSettings(BaseSettings):
    """Configuration for the JobMaster scraper, loaded from environment/.env.

    Attributes:
        web_base_url: Public site base; listing/detail pages.
        api_base_url: The api.il gateway host (no robots restriction
            stated there; only used for the facet-dictionary calls).
        max_jobs_per_run: Cap on detail pages fetched per run (window).
        max_discovery_requests: Cap on probe GETs during the cell
            walk; full rotation is ~1.3k probes at ~1.7 s each, so a
            capped run covers a head-major prefix of the cells — the
            same incremental-window philosophy the other capped sources
            use, just with request-count instead of a date cursor.
        fetch_delay_seconds: Politeness pause between detail fetches.
        request_timeout_seconds: Max time per request.
        max_retry_attempts / retry waits: like the other sources.
        user_agent: Browser-style UA; the site treats it as a normal
            browser client.
        discovery_seed_query: Hebrew-letter query that fills the
            groupBy facet counts; 'ה' is near-universal in Hebrew text.
    """

    model_config = SettingsConfigDict(
        env_prefix="JOBMASTER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    web_base_url: str = "https://www.jobmaster.co.il"
    api_base_url: str = "https://api.il.jobmaster.co.il"
    max_jobs_per_run: int = Field(default=400, ge=1)
    max_discovery_requests: int = Field(default=800, ge=1)
    fetch_delay_seconds: float = Field(default=0.25, ge=0.0)
    request_timeout_seconds: float = 30.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    discovery_seed_query: str = "ה"
