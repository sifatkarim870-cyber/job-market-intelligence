"""Zangia.mn-specific configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or window change is a one-line ``.env``
edit (prefix ``ZANGIA_MN_``), not a code change.

Zangia (``zangia.mn``, Mongolia's long-running job board) exposes two
keyless public JSON endpoints on its HR API host, both fully mapped
during scoping (2026-11-21):

* **``GET https://hr-api.zangia.mn/api/job/public/list/search``** returns
  ``{data, page, limit, total, totalPages}`` where ``data`` holds up to
  ``limit`` listing rows, newest-first by ``sortTime``. ``?page=N`` and
  ``?limit=N`` paginate; the default page size is 90 and ``limit`` accepts
  at least 500 (total was 6,099 rows at scoping). A listing row carries
  ``code`` (the URL slug), ``title``, ``company``, ``salary`` and
  ``location``.
* **``GET https://hr-api.zangia.mn/api/job/public/detail/<code>``**
  returns ``{data, message}`` with the complete record: HTML
  ``description`` / ``requirements`` / ``additional``, ``skills``,
  ``branch``, ``jobLevel``, ``timetype``, ``address`` and ``company``.

The public page URL is ``https://zangia.mn/job/<code>`` (HTTP 200).

robots.txt posture
-----------------
There is NO readable ``robots.txt`` anywhere on the property:
``zangia.mn/robots.txt``, ``www.zangia.mn/robots.txt``,
``hr-api.zangia.mn/robots.txt`` and ``new-api.zangia.mn/robots.txt`` all
return HTTP 404 (no policy file exists). RFC 9309 treats an unavailable
``robots.txt`` as "allow all", but this project's standing convention is
that an unreadable/absent policy is *unknown* pending an explicit
decision. The project owner reviewed the 404s and approved building this
source on 2026-11-21, with the 404s recorded as an observed fact rather
than silently treated as permission - matching the repo's precedent for
keyless API hosts (``api.p.hr.ge`` 404, ``cupid.51job.com`` 400,
``api.il.jobmaster.co.il`` 200, ``tjapi.timesjobs.com`` 502).

Two data facts shaped these defaults:

* **Salary is always stated.** Every sampled listing and detail row
  carried a populated ``salary`` object (``{id, phrase, min, max}``) in
  whole Mongolian tugrik (MNT), quoted monthly by the board's own
  convention; the cleaner still drops a non-positive bound and swaps a
  reversed pair rather than trusting the numbers blindly.
* **``fetch_delay_seconds`` defaults to 0.3** - one detail request is made
  per job, so a 200-row run is ~202 requests; pacing keeps the sweep
  polite without meaningfully lengthening it.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ZangiaSettings(BaseSettings):
    """Configuration for the Zangia.mn scraper, loaded from environment/.env.

    Attributes:
        list_url: The open GET search endpoint; the page number and window
            ride in the query string.
        detail_url_template: The open GET detail endpoint, with a
            ``{code}`` placeholder the client fills per job.
        web_base_url: Public site base, used only to make logs readable
            (the API returns the posting ``code``, not an absolute URL).
        start_page: First listing page to read (1-based, newest-first).
            CI always wants 1; a chunked backfill raises it to walk older
            pages.
        page_size: Rows requested per listing page. The API default is 90
            and ``limit`` accepts at least 500; 90 is kept as the polite
            default.
        max_jobs_per_run: Safety cap on jobs fetched per run. One detail
            request is made per job, so the default of 200 is ~3 listing
            pages plus 200 detail GETs. A local backfill raises it via
            ``ZANGIA_MN_MAX_JOBS_PER_RUN``.
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
        env_prefix="ZANGIA_MN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    list_url: str = "https://hr-api.zangia.mn/api/job/public/list/search"
    detail_url_template: str = "https://hr-api.zangia.mn/api/job/public/detail/{code}"
    web_base_url: str = "https://zangia.mn"
    start_page: int = Field(default=1, ge=1)
    page_size: int = Field(default=90, ge=1)
    max_jobs_per_run: int = Field(default=200, ge=1)
    fetch_delay_seconds: float = Field(default=0.3, ge=0.0)
    request_timeout_seconds: float = 40.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
