"""Configuration for the Job in Rwanda scraper.

Measured on the live site on 2026-10-18 rather than assumed:

  * **Discovery** is the **homepage**, not a listing path. ``/jobs`` is
    **HTTP 404** and ``/?page=2`` returns 0 new postings, so there is no pager at
    all: the single homepage carries **199** ``/job/<slug>`` links. That is the
    whole board in one request.

  * Detail pages carry **no schema.org JSON-LD and no ``og:`` meta tags**. The
    title lives in ``<title>`` as ``"<Job Title> | Job in Rwanda"``, and the body
    lives in ``.node__content``. So this is HTML extraction, not JSON-LD.

  * **There is no posting date anywhere on the page.** This is the trap, and it
    is a trap of omission rather than of shape. Six detail pages were inspected:
    four carry no date at all, and the two that do carry a date only ever carry
    a *deadline*, in prose --

        "The deadline for submission of applications is 19 October 2026 at 5:00 PM"
        "Application deadline Sunday 25 October 2026 - places filled on a rolling basis"
        "Application Deadline 28 November 2026 ."

    A regex that grabbed the first date it found would have written a
    **closing** date into ``posting_date`` on every row that had one -- a claim
    the site never makes. So ``posted_date`` is always ``None`` here and only a
    date in an explicitly deadline-shaped phrase is recorded, as ``closing_date``.

  * The company is not exposed structurally. It appears only inside the
    posting prose ("The Management of RATWA SACCO HUYE informs...",
    "ISCO SECURITY LTD"), which is not a field. ``company_name`` stays
  "Unknown employer" rather than being guessed out of a sentence.

robots.txt is real ``text/plain`` (1706 bytes): the ``User-agent: *`` group
allows ``/`` and disallows only ``/core/``, ``/profiles/`` and ``/README.txt``.
Job pages are permitted.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobInRwandaSettings(BaseSettings):
    """Configuration for the Job in Rwanda board."""

    model_config = SettingsConfigDict(env_prefix="JOBINRWANDA_", extra="ignore")

    base_url: str = Field(default="https://www.jobinrwanda.com", description="Site root.")
    listing_path: str = Field(
        default="/",
        description=(
            "The homepage is the listing: /jobs is HTTP 404 and ?page=2 adds "
            "nothing, so all 199 postings are on one page."
        ),
    )

    max_pages: int = Field(
        default=1,
        ge=1,
        le=200,
        description=(
            "Pages of the homepage to walk. The pager does not exist, so this is "
            "1 -- kept as a knob so a future pager is a config change."
        ),
    )

    max_jobs_per_run: int = Field(
        default=150,
        ge=1,
        description="Cap on postings persisted in one run (JOBINRWANDA_MAX_JOBS_PER_RUN).",
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA. No key or registration is involved.",
    )

    request_timeout_seconds: int = Field(default=60, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Detail pages are ~100 KB -- the largest in this batch. 1.0s keeps a
    #: 150-posting run around 5 minutes and no throttle was observed.
    inter_request_delay_seconds: float = Field(default=1.0, ge=0.0)

    fetch_description: bool = Field(
        default=True,
        description=(
            "Fetch each detail page for the title and body. The homepage carries "
            "only a path, so without this there is nothing to store."
        ),
    )

    stop_after_repeated_empty_pages: int = Field(default=2, ge=1)
    min_links_per_page: int = Field(
        default=5,
        ge=1,
        description="Tail threshold. The homepage carries 199 links.",
    )
