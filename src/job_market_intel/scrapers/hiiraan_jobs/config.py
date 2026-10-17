"""Configuration for the Hiiraan jobs scraper (Somalia).

Measured on the live site on 2026-10-18 rather than assumed:

  * **Discovery** is the listing page ``/jobs.php``, which links **16** postings
    as **PDF** files (Terms of Reference), e.g.
    ``/uploads/2026/jobs/08/1785793050_full-stacksoftwareengineer-tor.pdf``.
    There is **no working pager**: ``/jobs.php?page=2`` returns 0 new links.
  * Hrefs are **relative**.
  * Detail pages are **PDFs**, not HTML. Text is extracted with ``pypdf``
    (a declared dependency, not an ad-hoc install). The PDFs are well-structured
    Terms of Reference with labelled fields::

        Position Title: Full-Stack Software Engineer
        Department: Information Technology
        Position Level: Level 1 Officer
        Reports To: Head of Information Technology
        Employment Type: Full-time
        Location: Mogadishu, Somalia
        Deadline for submission: 17th August 2026, 11.59 PM Mogadishu time.

  * **No salary, no posting date, no company field.** The employer is the
    organization named in the background prose, which is not a field, so
    ``company_name`` stays "Unknown employer".
  * robots.txt: ``User-agent: *`` allows ``/`` and disallows ``/comments/`` and
    ``/social/``. PDF postings are permitted.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HiiraanJobsSettings(BaseSettings):
    """Configuration for the Hiiraan jobs board (Somalia)."""

    model_config = SettingsConfigDict(env_prefix="HIIRAAN_JOBS_", extra="ignore")

    base_url: str = Field(default="https://hiiraan.com", description="Site root.")
    listing_path: str = Field(default="/jobs.php", description="Server-rendered listing page.")

    max_pages: int = Field(
        default=1, ge=1, le=200, description="Pages to walk. The board has no pager."
    )
    max_jobs_per_run: int = Field(
        default=50, ge=1, description="Cap on postings persisted in one run."
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)", description="Identifying UA."
    )
    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Detail pages are ~270 KB PDFs. 1.5s is comfortably inside what the site
    #: tolerates; no throttle was observed.
    inter_request_delay_seconds: float = Field(default=1.5, ge=0.0)

    fetch_description: bool = Field(
        default=True,
        description="Fetch each PDF for its text. Listing pages carry only a path.",
    )

    stop_after_repeated_empty_pages: int = Field(default=2, ge=1)
    min_links_per_page: int = Field(
        default=5, ge=1, description="Tail threshold. Pages carry ~16 postings."
    )
