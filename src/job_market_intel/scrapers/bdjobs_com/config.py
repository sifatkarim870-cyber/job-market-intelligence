"""Bdjobs (bdjobs.com) scraper configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or window change is a one-line ``.env``
edit (prefix ``BDJOBS_COM_``), not a code change.

Bdjobs is Bangladesh's largest job board. Its public single-page app
(``https://bdjobs.com/h/``) is backed by two keyless JSON endpoints on the
``api.bdjobs.com`` host, both fully mapped during scoping (2026-11-21):

* **Search** -- ``GET
  https://api.bdjobs.com/jobs/api/v1/JobSearch/GetJobSearch`` with
  ``pg=N&rpp=100`` returns ``{message, statuscode, data[], premiumData[],
  common{total_records_found, totalpages, total_vacancies}}``. The feed is
  date-descending; ``rpp=100`` is accepted and the board reported
  ``total_records_found`` ~5,747 over ``totalpages`` 58.
* **Detail** -- ``GET
  https://api.bdjobs.com/jobs/api/v1/JobSubsystem/jobDetails`` with
  ``jobId=<id>&ln=1&IsCorporate=false`` returns ``{statuscode, message,
  data[{...}]}`` whose single object is the complete record: HTML
  ``JobDescription``, ``JobNature``, ``JobWorkPlace``, salary bounds,
  education/skills/experience, employer and a public logo URL.

The two URLs above are copied verbatim from the site's own bundled config
chunk (``https://bdjobs.com/h/chunk-SMUS2CWI.js``, keys ``searchEndpoint``
and ``detailsApiBaseUrl``), so they are the endpoints the app itself calls.

robots.txt posture
------------------
Read as RFC 9309 groups, the board's two HTML hosts are BOTH closed to a
generic crawler:

* ``https://bdjobs.com/robots.txt`` (HTTP 200) declares a ``User-agent: *``
  group that disallows a list of asset paths and then a SECOND
  ``User-agent: *`` group with ``Disallow: /``. RFC 9309 combines rules for
  the same user-agent, so the effective policy for ``*`` is disallow-all.
* ``https://jobs.bdjobs.com/robots.txt`` (HTTP 200) is the same shape: the
  ``*`` group also ends in ``Disallow: /``.

The API host is separate and open: ``https://api.bdjobs.com/robots.txt``
answers **HTTP 404** (an IIS HTML not-found page, no policy file). RFC 9309
treats a 4xx robots.txt as "unavailable" and permits access -- the same
allow-on-404 reading this repo applied to ``jobs.smartrecruiters.com`` for
``llv_li``. Accordingly this scraper fetches **only** ``api.bdjobs.com``
and never any ``bdjobs.com`` / ``jobs.bdjobs.com`` HTML page; the public
``https://bdjobs.com/h/details/<id>`` URL it stores is a link for humans,
never a request.

Data facts that shaped these defaults (measured 2026-11-21):

* **Salary is often undisclosed.** ``ShowSalary`` is ``"0"`` on some rows
  and the bounds are ``0``; many disclosed rows are "Negotiable" (bounds
  ``0``); the rest carry ``Tk. <min> - <max> (Monthly)``. The cleaner maps
  positive bounds and treats 0 / "Negotiable" / ``ShowSalary == "0"`` as
  undisclosed. Currency is ``BDT`` and pay period is monthly by convention.
* **Employment and work mode are separate.** ``JobNature`` is usually
  "Full Time"; ``JobWorkPlace`` is "Work at office", "Work from home" or
  blank. The cleaner maps the first onto ``ref.employment_types`` and the
  second onto ``ref.remote_work_types``.
* **``fetch_delay_seconds`` defaults to 0.25** -- one detail request is
  made per job, so a 200-row run is ~202 requests; pacing keeps the sweep
  polite without meaningfully lengthening it.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BdjobsSettings(BaseSettings):
    """Configuration for the Bdjobs scraper, loaded from environment/.env.

    Attributes:
        search_url: The keyless GET search endpoint.
        detail_url: The keyless GET detail endpoint.
        web_base_url: Public SPA base, used only to make logs readable.
        detail_page_base: Public detail page prefix; the stored
            ``original_url`` is ``detail_page_base + <jobId>``.
        rows_per_page: Rows requested per search page (the API accepts
            100).
        max_pages: Safety ceiling on search pages walked per run.
        max_jobs_per_run: Safety cap on jobs fetched per run. One detail
            request is made per job, so the default of 200 is ~2 search
            pages plus 200 detail GETs. CI's scheduled run uses this
            default; a local backfill raises it via
            ``BDJOBS_COM_MAX_JOBS_PER_RUN``.
        fetch_delay_seconds: Politeness pause between detail GETs.
        request_timeout_seconds: Max time to wait for one request.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff.
        user_agent: Browser-style User-Agent; the endpoints serve fine to
            one, and identifying honestly is polite regardless.
    """

    model_config = SettingsConfigDict(
        env_prefix="BDJOBS_COM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    search_url: str = "https://api.bdjobs.com/jobs/api/v1/JobSearch/GetJobSearch"
    detail_url: str = "https://api.bdjobs.com/jobs/api/v1/JobSubsystem/jobDetails"
    web_base_url: str = "https://bdjobs.com"
    detail_page_base: str = "https://bdjobs.com/h/details/"
    rows_per_page: int = Field(default=100, ge=1, le=100)
    max_pages: int = Field(default=60, ge=1)
    max_jobs_per_run: int = Field(default=200, ge=1)
    fetch_delay_seconds: float = Field(default=0.25, ge=0.0)
    request_timeout_seconds: float = 40.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
