"""Configuration for the Wellfound scraper (angel.co's successor).

Established by probing the live site on 2026-10-14, not assumed:

  * **Discovery works only on ``/location/<country>`` and
    ``/role/l/<role>/<country>``.** Both paginate with ``?page=N`` and both
    yield ~45-58 *distinct* job links per page. ``/jobs`` returns HTTP 200 and
    looks paginated (it renders a ``page=N`` pager), but the parameter is
    ignored: every page from 1 to 11 returned the identical 43 job ids and zero
    new ones. Walking it would spend the whole request budget re-reading page
    1 while reporting progress. Only ``/location/...`` is walked here.

  * Detail pages carry a schema.org ``JobPosting`` JSON-LD block with 14 of 14
    fields present across the postings measured: title, identifier, employmentType,
    hiringOrganization (name, website, logo, per-office coordinates),
    description, datePosted, jobLocation (with coordinates),
    baseSalary (currency + unitText + minValue/maxValue), jobBenefits,
    industry, directApply and image.

  * ``/location/canada`` returns 404. United Kingdom, Germany and France all
    return 200. The default listing set is therefore the countries verified to
    answer, not a guess at what exists.

Compliance
----------
robots.txt is fetched as HTTP 200 but served with ``Content-Type: text/html``
(a site misconfiguration -- it is real plain-text robots content, and parsing
it as HTML would make every path look allowed). Its rules for ``User-agent: *``
are exactly::

    Disallow: /_jobs/
    Disallow: /*?after_sign_in=*
    Disallow: /*?inFrame=*

This scraper requests ``/location/...``, ``/role/...`` and ``/jobs/<id>-<slug>``.
``/jobs/`` is a different path from the disallowed ``/_jobs/`` and is therefore
permitted by the rule as written.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WellfoundSettings(BaseSettings):
    """Configuration for the Wellfound startup-job board."""

    model_config = SettingsConfigDict(env_prefix="WELLFOUND_", extra="ignore")

    base_url: str = Field(default="https://wellfound.com", description="Site root.")

    #: Listing pages to walk. Only paths verified to paginate are here; see the
    #: module docstring for why ``/jobs`` is absent.
    listing_paths: list[str] = Field(
        default_factory=lambda: [
            "/location/united-states",
            "/location/united-kingdom",
            "/location/germany",
            "/location/france",
            "/location/netherlands",
            "/location/spain",
            "/location/ireland",
            "/location/india",
            "/role/l/software-engineer/united-states",
            "/role/l/product-manager/united-states",
            "/role/l/data-scientist/united-states",
            "/role/l/designer/united-states",
            "/role/l/marketing/united-states",
            "/role/l/sales/united-states",
        ],
        description=(
            "Server-rendered listing pages. /location/canada 404s, so it is not "
            "listed; add paths here as they are verified to answer 200."
        ),
    )

    max_pages_per_listing: int = Field(
        default=2,
        ge=1,
        le=60,
        description=(
            "Pages per listing. One page is ~50 distinct jobs and costs a "
            "~700 KB download, so this is the main request-budget knob. "
            "Page links run to 83 on /location/united-states."
        ),
    )

    max_jobs_per_run: int = Field(
        default=300,
        ge=1,
        description=("Cap on postings persisted in one run. Raise via WELLFOUND_MAX_JOBS_PER_RUN."),
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA. No key or registration is involved.",
    )

    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Listing pages are 600-860 KB and detail pages ~100 KB. A 1.5s floor keeps
    #: a run polite without making a 300-posting run take 10 minutes.
    inter_request_delay_seconds: float = Field(default=1.5, ge=0.0)

    fetch_description: bool = Field(
        default=True,
        description=(
            "Fetch each detail page for the JSON-LD block. The listing pages "
            "carry only a link and a slug, so without this there is nothing to "
            "store but ids."
        ),
    )

    #: Stop walking a listing once this many consecutive pages yield no new job
    #: id. Catches the `/jobs?page=N` failure mode if a listing path is ever
    #: added that silently ignores its page parameter.
    stop_after_repeated_empty_pages: int = Field(default=2, ge=1)
