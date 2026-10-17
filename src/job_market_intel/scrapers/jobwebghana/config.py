"""Configuration for the Jobweb Ghana scraper.

Measured on the live site on 2026-10-18 rather than assumed:

  * **Discovery** is ``/jobs/`` with **path-based** pagination,
    ``/jobs/page/2/`` -- which returned **13 new** postings. The hrefs are
    **absolute** (measured 20 absolute, 0 relative), so the pattern makes the
    host prefix optional; Angola Emprego was the same way and a relative-only
    pattern there matched nothing at all on a board serving 15 postings a page.

  * robots.txt disallows ``/*?*`` -- every query string. That is why pagination
    uses ``/jobs/page/2/`` and **never** ``?page=2``: the path form is permitted,
    the query form is not.

  * Detail pages carry a schema.org ``JobPosting``. Measured on 5 postings:
    ``title``, ``description``, ``datePosted``, ``validThrough``,
    ``employmentType`` (``"FULL_TIME"``, a bare string), ``hiringOrganization``
    (name + ``sameAs``), ``jobLocation`` (streetAddress, locality, postalCode,
    region) and ``baseSalary``. **No ``identifier``**, so the URL slug is the key.

  * ``baseSalary`` nests ``value``/``minValue``/``maxValue``/``unitText`` under
    ``value`` -- a **seventh** distinct layout in this codebase -- and
    ``unitText`` is ``"MONTH"``.

The salary is a site-wide placeholder
-------------------------------------
**5 of 5 measured postings carry a byte-identical** ``baseSalary``::

    {"currency": "GHS",
     "value": {"value": "1500", "minValue": "1500", "maxValue": "8000",
               "unitText": "MONTH"}}

across a Chief Executive Officer, a CCTV Controller and an Accounts Clerk. Those
roles do not share one salary band, and ``value`` duplicating ``minValue`` is the
signature of a template rather than a posted figure. Storing it would put the
same invented 1500-8000 GHS range on every Ghanaian row and poison any salary
analysis for the country -- in a schema.org shape, so it would look legitimate.
It is therefore rejected in the cleaner, the same way CareerJunction's
``"R Undisclosed"`` is.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobwebGhanaSettings(BaseSettings):
    """Configuration for the Jobweb Ghana board."""

    model_config = SettingsConfigDict(env_prefix="JOBWEBGHANA_", extra="ignore")

    base_url: str = Field(default="https://jobwebghana.com", description="Site root.")
    listing_path: str = Field(default="/jobs/", description="Server-rendered listing page.")
    #: Path-based page template. Measured: ``/jobs/page/2/`` returns 13 new
    #: postings. A query form (``?page=2``) is used instead of this only by
    #: mistake -- robots.txt disallows ``/*?*``.
    page_path_template: str = Field(
        default="/jobs/page/{page}/",
        description="Path-based pagination template.",
    )

    max_pages: int = Field(
        default=6,
        ge=1,
        le=200,
        description="Listing pages to walk. ~22 postings on page 1, ~13 per page after.",
    )

    max_jobs_per_run: int = Field(
        default=80,
        ge=1,
        description="Cap on postings persisted in one run (JOBWEBGHANA_MAX_JOBS_PER_RUN).",
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA. No key or registration is involved.",
    )

    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Detail pages are ~74 KB. 1.5s is comfortably inside what the site
    #: tolerates; no throttle was observed.
    inter_request_delay_seconds: float = Field(default=1.5, ge=0.0)

    fetch_description: bool = Field(
        default=True,
        description=(
            "Fetch each detail page for the JSON-LD block. Listing pages carry "
            "only a path, so without this there is nothing to store."
        ),
    )

    stop_after_repeated_empty_pages: int = Field(default=2, ge=1)
    min_links_per_page: int = Field(
        default=5,
        ge=1,
        description="Tail threshold. Page 1 carries ~22 postings.",
    )
