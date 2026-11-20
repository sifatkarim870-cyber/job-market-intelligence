"""TimesJobs-specific configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or window change is a one-line ``.env``
edit (prefix ``TIMESJOBS_IN_``), not a code change.

TimesJobs (``timesjobs.com``, an India-headquartered job board) exposes
two keyless JSON endpoints, both fully mapped during scoping
(2026-11-21):

* **``POST https://tjapi.timesjobs.com/search/api/v1/search/jobs/list``**
  with body ``{"keyword", "location", "experience", "page", "size",
  "jobFunctions", "company", "industry", "functionAreaId",
  "jobFunction"}`` returns ``{total, page, size, totalPages, jobs}``.
  ``size`` accepts at least 500 (the site's own UI asks for 100);
  the default feed is date-descending by ``postDate`` and past the last
  page ``jobs`` is simply empty. The total was ~185,680 live rows at
  scoping, of which ``location="India"`` narrowed to ~10,249 with every
  row's location collapsed to the bare string "India".
* **``GET https://tjapi.timesjobs.com/job-api/api/jobs/public/<token>``**
  returns the complete record. ``token`` is everything after ``jobid-``
  in a listing row's ``jobDetailUrl`` (including its trailing
  ``&source=srp``); it must be URL-encoded as a single path segment
  (``urllib.parse.quote(token, safe="")``). The site's own
  ``__PLUS__``/``__SLASH__`` escape tokens resolve to HTTP 200 unchanged.

robots.txt posture
------------------
The main/apex host's ``robots.txt`` is readable and permissive:
``User-agent: *`` / ``Allow: /*`` with only ``/timesJobWebApp/``,
``/logout.html``, ``/AutoLogin.html`` and ``/times_logout`` disallowed,
none of which this client touches. The API host
``tjapi.timesjobs.com`` returns HTTP 502 for both ``/robots.txt`` and
``/`` (its nginx gateway only answers valid API calls), so its policy is
unreadable. The project owner reviewed this and approved building the
source on 2026-11-21, with the 502 recorded as an observed fact rather
than silently treated as permission - matching the repo's precedent for
keyless API hosts (``api.p.hr.ge`` 404, ``cupid.51job.com`` 400,
``api.il.jobmaster.co.il`` 200).

Two data facts shaped these defaults:

* **Salary is effectively hidden.** Every sampled detail row carried
  ``hideCtcFromCandidate: true`` with ``minCtc``/``maxCtc`` at ``-1``
  (30/30 and 100/100 listing rows alike), so the salary columns are
  mostly empty - the cleaner still maps a positive ``minCtc``/``maxCtc``
  whenever a row does disclose it. Currency is always ``INR`` on the
  listing (``ctcCurrency`` on the detail is the raw enum ``"r"``).
* **``fetch_delay_seconds`` defaults to 0.25** - one detail request is
  made per job, so a 200-row run is ~202 requests; pacing keeps the
  sweep polite without meaningfully lengthening it.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TimesjobsSettings(BaseSettings):
    """Configuration for the TimesJobs scraper, loaded from environment/.env.

    Attributes:
        list_url: The open POST search endpoint; the page number and
            window ride in the JSON body.
        detail_url_template: The open GET detail endpoint, with a
            ``{token}`` placeholder the client fills per job.
        web_base_url: Public site base, used only to make logs readable
            (the API returns absolute ``jobDetailUrl`` values).
        keyword: Optional search keyword sent on every listing page
            (empty = the board's default mixed feed).
        location: Optional location filter (empty = no filter; the board
            collapses a country filter such as ``India`` to the bare
            country string, so it is left empty by default to keep the
            per-city location text).
        page_size: Rows requested per listing page. The API accepts at
            least 500; the site's own UI uses 100, which is the default
            here.
        start_page: First listing page to read (1-based, newest-first).
            CI always wants 1; a chunked backfill raises it to walk older
            pages.
        max_jobs_per_run: Safety cap on jobs fetched per run. One detail
            request is made per job, so the default of 200 is ~2 listing
            pages plus 200 detail GETs. A local backfill raises it via
            ``TIMESJOBS_IN_MAX_JOBS_PER_RUN``.
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
        env_prefix="TIMESJOBS_IN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    list_url: str = "https://tjapi.timesjobs.com/search/api/v1/search/jobs/list"
    detail_url_template: str = "https://tjapi.timesjobs.com/job-api/api/jobs/public/{token}"
    web_base_url: str = "https://www.timesjobs.com"
    keyword: str = ""
    location: str = ""
    page_size: int = Field(default=100, ge=1)
    start_page: int = Field(default=1, ge=1)
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
