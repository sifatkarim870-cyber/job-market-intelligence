"""Configuration for the Apna scraper (India).

Everything here was measured on the live site on 2026-10-16, over a 30-posting
census and a 6-page discovery walk, rather than assumed:

  * **Discovery** is ``/jobs?page=N``. Exactly **25** links per page, and the
    pager is real: 150 distinct paths over 6 pages with 25 new on *every* page.
    This is the opposite of Wellfound (whose ``page`` parameter is ignored) and
    of mustakbil (41 identical links on pages 1, 2 and 3).

  * robots.txt is real ``text/plain``, 160 bytes. The governing ``*`` group
    disallows exactly one path, ``/*.infra.apna.co/``, which is an internal
    infrastructure host and not part of the job surface. ``/jobs``,
    ``/job/<city>/<slug>-<id>``, ``/company`` and ``/search`` are all fetchable,
    confirmed with ``urllib.robotparser``.

  * The detail payload is the richest in the corpus: **30 of 30** postings
    measured carried ``baseSalary``, every one of them a ``minValue``/``maxValue``
    band with ``unitText: "MONTH"``, plus ``skills`` (15 of 30, up to 11
    entries), ``industry``, ``occupationalCategory``, ``directApply`` and
    ``applicantLocationRequirements``.

  * Descriptions run 23-4282 characters (mean 835). **16 of 30 are shorter than
    100 characters**, so a 100-character "substantial description" floor -- the
    kind every other validator here uses -- would fail more than half of a
    perfectly healthy batch. See :mod:`.validator`.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApnaSettings(BaseSettings):
    """Configuration for the Apna India job board."""

    model_config = SettingsConfigDict(env_prefix="APNA_", extra="ignore")

    base_url: str = Field(default="https://apna.co", description="Site root.")
    listing_path: str = Field(default="/jobs", description="Server-rendered listing page.")

    max_pages: int = Field(
        default=8,
        ge=1,
        le=200,
        description=(
            "Listing pages to walk. 25 postings per page, so 8 pages is ~200. "
            "Measured to paginate cleanly to at least 6 pages."
        ),
    )

    max_jobs_per_run: int = Field(
        default=200,
        ge=1,
        description="Cap on postings persisted in one run (APNA_MAX_JOBS_PER_RUN).",
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA. No key or registration is involved.",
    )

    request_timeout_seconds: int = Field(default=45, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: Listing pages are ~1.0 MB -- among the largest served in this project,
    #: second only to Wellfound's 600-860 KB pages at three figures. 1.2s keeps
    #: a 200-posting run around five minutes.
    inter_request_delay_seconds: float = Field(default=1.2, ge=0.0)

    fetch_description: bool = Field(
        default=True,
        description=(
            "Fetch each detail page for the JSON-LD block. Listing pages carry "
            "only a path, so without this there is nothing to store."
        ),
    )

    stop_after_repeated_empty_pages: int = Field(
        default=2,
        ge=1,
        description=(
            "Stop after this many consecutive pages yield no new posting id. "
            "Guards the case where the listing ignores ?page= -- measured on "
            "Wellfound and mustakbil, so it is a real failure mode here."
        ),
    )

    min_links_per_page: int = Field(
        default=5,
        ge=1,
        description=(
            "A page with fewer links than this is treated as the tail -- but its "
            "links are still collected first, because a short final page still "
            "holds real postings. Pages carry 25."
        ),
    )
