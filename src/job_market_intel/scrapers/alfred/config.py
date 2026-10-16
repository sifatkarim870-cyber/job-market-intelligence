"""Configuration for the Alfred scraper (Iceland).

Measured on the live site on 2026-10-16 rather than assumed.

Discovery is the interesting part
---------------------------------
The homepage embeds a full job feed in ``__NEXT_DATA__`` --
``props.pageProps.jobs`` -- reporting ``totalCount: 572`` and
``totalPages: 22``. It looks like the obvious source. It is not usable:

* it serves only **27** records per response;
* every pagination attempt returns a **byte-identical** 667,028-byte page with
  **0 new** ids: ``/?page=2``, ``/?p=2`` and ``/?page=3`` are all the same
  document. It is a statically generated page that renders page 1 forever;
* ``/starf?page=2`` and ``/page/2`` are HTTP 404.

robots.txt disallows ``/api/*`` and every filter parameter
(``*jobtypes=*``, ``*tags=*``, ``*zips=*``, ``*cat=*``), so neither the JSON API
nor the faceted views are available by the site's own rules.

What robots *does* offer is ``Sitemap: https://alfred.is/sitemap.xml``, and that
is a sitemap index with two children. ``sitemap-jobs.xml`` holds **624**
``/starf/`` URLs. Using the sitemap the site nominates for crawlers is both the
compliant route and the only one that reaches the whole board, so discovery
reads the sitemap and not the homepage feed.

Payload
-------
Measured over 10 detail pages: 9 of 10 JSON-LD fields on every posting
(``title``, ``description``, ``datePosted``, ``hiringOrganization``,
``directApply``, ``employmentType``, ``validThrough``) with ``jobLocation`` on 7
of 10.

Three things that will otherwise be assumed and are not true here:

* **No ``identifier`` at all** (0 of 10). The stable key is the URL slug.
* **No ``baseSalary`` at all** (0 of 10). Alfred publishes no salary, so
  ``salary_disclosed`` is always ``False`` for this source. There is no period
  to map and nothing for ``ck_job_salaries_pay_period`` to reject.
* Descriptions run **17 to 2656** characters, because a handful of sitemap
  entries are "general application" pages rather than real vacancies. The
  validator floor is set accordingly.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AlfredSettings(BaseSettings):
    """Configuration for the Alfred Iceland job board."""

    model_config = SettingsConfigDict(env_prefix="ALFRED_", extra="ignore")

    base_url: str = Field(default="https://alfred.is", description="Site root.")

    #: The sitemap index, which is the only compliant complete discovery route.
    sitemap_url: str = Field(
        default="https://alfred.is/sitemap.xml",
        description="Sitemap index named in robots.txt.",
    )

    #: Preferred child. The index also contains sitemap-web.xml, which holds 5
    #: non-job URLs and is skipped rather than filtered.
    jobs_sitemap_name: str = Field(
        default="sitemap-jobs.xml",
        description="Child sitemap carrying the /starf/ URLs.",
    )

    #: Used only if the index is replaced by a flat urlset.
    jobs_sitemap_url: str = Field(
        default="https://alfred.is/sitemap-jobs.xml",
        description="Fallback if sitemap_url is a urlset rather than an index.",
    )

    detail_path_prefix: str = Field(
        default="/starf/",
        description=(
            "Only URLs under this prefix are postings. The web sitemap and the "
            "site's own category pages share the domain."
        ),
    )

    max_jobs_per_run: int = Field(
        default=150,
        ge=1,
        description=(
            "Cap on postings persisted in one run (ALFRED_MAX_JOBS_PER_RUN). "
            "The jobs sitemap holds 624 URLs."
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

    #: Detail pages are 240-250 KB, among the largest served in this project.
    inter_request_delay_seconds: float = Field(default=1.0, ge=0.0)

    fetch_description: bool = Field(
        default=True,
        description=(
            "Fetch each detail page for the JSON-LD block. The sitemap gives "
            "URLs only -- no title, employer, dates or description -- so "
            "without this there is nothing to store."
        ),
    )

    drop_general_application_pages: bool = Field(
        default=True,
        description=(
            "A few sitemap entries are 'Almenn umsökn' (general application) "
            "pages rather than vacancies. Their descriptions run 17-200 "
            "characters and describe the employer's business instead of a job. "
            "They are dropped, and the count kept in the run report so the "
            "exclusion is visible rather than silent."
        ),
    )
