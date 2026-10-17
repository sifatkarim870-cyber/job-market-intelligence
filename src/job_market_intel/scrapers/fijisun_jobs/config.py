"""Configuration for the Fiji Sun jobs scraper (Fiji).

Measured on the live site on 2026-10-18 rather than assumed:

  * **Discovery** is ``/jobs`` with a **path-based** pager: ``/jobs/browse``
    returns **2 new** postings. ``/jobs/page/2`` and ``/jobs?page=2`` both
    return 0 new, so ``/jobs/browse`` is the real pager and the query form is
    dead.
  * Hrefs are **relative** (measured 8 relative, 0 absolute).
  * Detail pages carry **no schema.org JSON-LD**. The **``og:title`` and
    ``og:description`` meta tags are SITE-wide** ("Fiji Sun - Your Trusted
    Source for Fiji News") and must **not** be used -- a parser trusting them
    would store the site's name as every job's title.
  * The title is in ``<title>`` as ``"<Job Title> at <Company>  | Fiji Sun Jobs"``
    (note the **double space** before the pipe) and in ``<h1>`` as the bare
    title. The company comes from the ``<h1>``'s parent text minus the ``<h1>``.
  * The ``Job overview`` block carries labelled rows: ``Posted``, ``Salary``,
    ``Openings``, ``Experience``, ``Type``, ``Location``, ``Closes``. The
    description is in ``.mt-6.whitespace-pre-line.font-serif.text-neutral-700``.
  * The posting date is **relative** ("Posted 1 week ago", "Posted 3 days ago")
    and the closing date is **absolute** ("Closes 5 November 2026"). Only the
    posting date is derived; the closing date is read from the ``Closes`` row.
  * ``Salary`` reads ``"T.B.D."`` on every measured posting -- not a figure.
  * robots.txt: ``User-agent: *`` allows ``/`` and disallows ``/api/``,
    ``/admin`` and ``/todays-paper/``. Job pages are permitted.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FijiSunJobsSettings(BaseSettings):
    """Configuration for the Fiji Sun jobs board."""

    model_config = SettingsConfigDict(env_prefix="FIJISUN_JOBS_", extra="ignore")

    base_url: str = Field(default="https://fijisun.com.fj", description="Site root.")
    listing_path: str = Field(default="/jobs", description="Server-rendered listing page.")
    #: Path-based page template. Measured: ``/jobs/browse`` returns 2 new postings.
    page_path_template: str = Field(default="/jobs/browse", description="Pagination path.")

    max_pages: int = Field(
        default=6,
        ge=1,
        le=200,
        description="Listing pages to walk. ~8 postings per page.",
    )

    max_jobs_per_run: int = Field(
        default=50,
        ge=1,
        description="Cap on postings persisted in one run (FIJISUN_JOBS_MAX_JOBS_PER_RUN).",
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA. No key or registration is involved.",
    )

    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Detail pages are ~275 KB -- the largest in this batch. 1.5s is
    #: comfortably inside what the site tolerates; no throttle was observed.
    inter_request_delay_seconds: float = Field(default=1.5, ge=0.0)

    fetch_description: bool = Field(
        default=True,
        description=(
            "Fetch each detail page for the title, body and metadata. Listing pages "
            "carry only a path, so without this there is nothing to store."
        ),
    )

    stop_after_repeated_empty_pages: int = Field(default=2, ge=1)
    min_links_per_page: int = Field(
        default=5,
        ge=1,
        description="Tail threshold. Pages carry ~8 postings.",
    )
