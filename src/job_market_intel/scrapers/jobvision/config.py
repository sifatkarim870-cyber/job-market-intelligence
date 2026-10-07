"""Jobvision-specific configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or window change is a one-line ``.env``
edit (prefix ``JOBVISION_``), not a code change.

Jobvision (jobvision.ir — "جاب ویژن", an Iranian job platform) exposes
two unauthenticated endpoints, both confirmed live during scoping
(2026-10-07):

* **Discovery — ``/sitemap/jobposts.xml``** (declared in an open
  robots.txt alongside a ``sitemap.xml`` index): a 27 MB document with
  **60,191 unique job URLs** (``/jobs/{id}/{persian-slug}``, each with a
  ``lastmod``) interleaved with company-logo/job-image URLs. The entries
  are **not** ordered newest-first (sampled lastmods run
  10-04, 09-29, 09-12, 09-24, …), so — unlike a newest-first source —
  a capped window only makes progress if known ids are excluded at
  selection time: this client therefore takes the same skip-known
  exclusion Glints' client does (``pipeline`` passes
  ``repository.get_all_source_job_ids``). The top of the document is
  still recent-heavy, so once coverage is complete the first unseen
  entries are effectively the newest arrivals.
* **Detail — ``candidateapi.jobvision.ir/api/v1/JobPost/Detail?jobPostId=…``**
  returns ~8 KB of JSON inside the envelope ``{isSuccess, statusCode,
  message, data}`` with **no auth, no cookies, no referrer** — the same
  API the site's own SSR page embeds (as an Angular ``ng-state`` blob).
  ``data`` carries ~40 keys: title, HTML description, ``salary`` (or
  null), ``workType``, activation/expire timestamps, location,
  categories, software/language requirements, company (name/logo/
  industries), and ``isExpired``/``isRemote``/``isInternship`` flags.

Two data facts shaped these defaults:

* **``request_timeout_seconds`` is 90** (other sources use 25): the
  sitemap is a 27 MB single document and cross-border fetches of it
  were observed to exceed 4 minutes during scoping; the detail API
  answers in ~1 s, so the larger ceiling costs nothing there.
* **Salary is expressed in millions of Toman** (``salary.min=26`` /
  ``salary.max=30`` beside ``titleFa: "26 - 30 میلیون تومان"`` /
  ``titleEn: "26 - 30 Million Tomans"``) — the raw model keeps those
  source units and ``cleaning/jobvision_cleaner.py`` scales them to
  whole Toman (currency ``IRT``).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobvisionSettings(BaseSettings):
    """Configuration for the Jobvision scraper, loaded from environment/.env.

    Attributes:
        web_base_url: Public site base; a job's canonical URL comes from
            the sitemap and is stored verbatim as ``original_url``.
        sitemap_url: The open job-posts sitemap used for discovery
            (~60k job URLs; 27 MB).
        detail_api_url: The unauthenticated JSON detail endpoint; the
            client appends ``?jobPostId={id}``.
        max_jobs_per_run: Safety cap on unique jobs fetched per run.
            The default of 400 mirrors the other CI windows — CI's
            skip-known window catches what it has not seen; the local
            full backfill raises it via ``JOBVISION_MAX_JOBS_PER_RUN``.
        fetch_delay_seconds: Politeness pause between detail fetches
            (a full-corpus crawl makes ~60k of them).
        request_timeout_seconds: Max time to wait for one request; 90
            because discovery downloads a 27 MB sitemap (see module
            docstring).
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff.
        user_agent: Browser-style User-Agent; both endpoints serve
            fine to one, and identifying honestly is polite regardless.
    """

    model_config = SettingsConfigDict(
        env_prefix="JOBVISION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    web_base_url: str = "https://jobvision.ir"
    sitemap_url: str = "https://jobvision.ir/sitemap/jobposts.xml"
    detail_api_url: str = (
        "https://candidateapi.jobvision.ir/api/v1/JobPost/Detail"
    )
    max_jobs_per_run: int = Field(default=400, ge=1)
    fetch_delay_seconds: float = Field(default=0.15, ge=0.0)
    request_timeout_seconds: float = 90.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
