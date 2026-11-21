"""ANPE Mali (anpe-mali.org) scraper configuration.

Same role as every other source's ``config.py``: values loaded through
``pydantic-settings`` so a URL or window change is a one-line ``.env``
edit (prefix ``ANPE_MALI_``), not a code change.

The source (``anpe-mali.org``, Mali's national employment agency -- "ANPE
MALI, Agence Nationale Pour l'Emploi, Republique du Mali, Service public
de l'emploi") is a WordPress site built on the WP Job Manager plugin, and
its public REST API is keyless and readable:

* ``GET /wp-json/wp/v2/job-listings?per_page=100&page=N`` returns the job
  post type as a JSON array; ``X-WP-Total`` reported 15 rows at scoping
  (2026-11-21), so the whole board fits on one 100-row page. The board's
  own sitemap (``/wp-sitemap-posts-job_listing-1.xml``) lists the same 15
  ``/poste/<slug>/`` URLs, confirming the count.
* The listing object carries ``{id, date, modified, link, slug,
  title.rendered, content.rendered, meta, job-types, job-categories,
  class_list, _embedded}``. The structured fields WP Job Manager exposes
  live under ``meta`` (``_job_location``, ``_company_name``,
  ``_application``, ``_remote_position``, ``_job_salary`` ...) and under
  ``job-types`` (term ids) / ``class_list`` (``job-type-<slug>``).
* The old ``anpe.ml`` domain the 2026-10-04 sweep recorded no longer
  resolves (NXDOMAIN); ``anpe-mali.org`` is the live replacement site.

robots.txt posture
------------------
``https://anpe-mali.org/robots.txt`` is readable (HTTP 200): ``User-agent:
*`` / ``Disallow: /wp-admin/`` / ``Allow: /wp-admin/admin-ajax.php`` plus a
``Sitemap:`` line. ``/wp-admin/`` is never fetched, and the ``/wp-json/``
path this scraper uses is not disallowed, so the policy is respected.

Data facts that shaped these defaults (measured 2026-11-21):

* **No salary is ever stated.** ``meta._job_salary`` (and its
  ``_job_salary_currency`` / ``_job_salary_unit`` companions) is the empty
  string on all 15 listings, so the cleaner never fabricates a bound;
  currency is XOF and the required pay period takes the documented inert
  default.
* **Location is a free-text field** (``meta._job_location``): "Bamako" on
  eight rows, "Mali"/"MALI" on three, "Sur site" on four and empty on one.
  "Sur site" is a work arrangement, not a place, so it is dropped from the
  location and recorded as ``on_site`` instead.
* **Contract type is a taxonomy**: ``job-types``/``class_list`` carry CDI,
  CDD, Interim, Independant or Stage; the cleaner maps the slugs it
  recognises and leaves multi-value rows unset rather than guessing.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnpeMaliSettings(BaseSettings):
    """Configuration for the ANPE Mali scraper, from env/.env.

    Attributes:
        base_url: Public site base.
        listings_url: The keyless WP Job Manager REST endpoint.
        per_page: Rows per page; WordPress caps this at 100.
        max_pages: Safety ceiling on pages walked per run.
        max_jobs_per_run: Safety cap on listings kept per run.
        fetch_delay_seconds: Politeness pause between page GETs.
        request_timeout_seconds: Read timeout for one page.
        max_retry_attempts: Total attempts (including the first) before a
            transient failure is fatal.
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff.
        user_agent: Browser-style User-Agent; the REST API serves fine to
            one, and identifying honestly is polite regardless.
    """

    model_config = SettingsConfigDict(
        env_prefix="ANPE_MALI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_url: str = "https://anpe-mali.org"
    listings_url: str = "https://anpe-mali.org/wp-json/wp/v2/job-listings"
    per_page: int = Field(default=100, ge=1, le=100)
    max_pages: int = Field(default=5, ge=1)
    max_jobs_per_run: int = Field(default=200, ge=1)
    fetch_delay_seconds: float = Field(default=1.0, ge=0.0)
    request_timeout_seconds: float = 45.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 2.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
