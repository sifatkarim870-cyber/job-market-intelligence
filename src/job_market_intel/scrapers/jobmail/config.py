"""Configuration for the JobMail scraper (South Africa).

Measured on the live site on 2026-10-19, not assumed:

* **No browser, no key, no proxy.** Plain ``requests`` serves both the listing
  and the detail page, and robots.txt disallows only ``/setup-alerts/*``.

* **The listing is server-rendered** and paginates cleanly::

      /jobs/          -> 20 postings
      /jobs/page2     -> 20 more
      /jobs/page400   -> 7,980 distinct postings and still going

  So the board holds **at least 8,000 postings** for a country the corpus
  covered with 178 rows.

* **Every card carries its own id** in the element's ``id`` attribute --
  ``<div class="results-item" id="results-item-7568798">`` -- and again in the
  link's slug, ``...-id-7568798``. Two independent carriers, so a card missing
  one still yields the other.

* **The listing card carries a salary.** ``div.job-info`` holds either a rand
  range -- ``R20 000,00 - R30 000,00`` -- or the words **"Market Related"**,
  which is a salary that is deliberately not a figure. The cadence is the
  sibling div: ``PER MONTH``.

* **The detail page carries a schema.org ``JobPosting``** with
  ``title``, ``description`` (measured 1,432-5,510 characters), ``datePosted``,
  ``validThrough``, ``employmentType``, ``hiringOrganization.name`` and
  ``identifier.value`` -- and a numeric ``baseSalary`` on some postings
  (``{"currency": "ZAR", "value": {"minValue": 20000, "maxValue": 30000,
  "unitText": "MONTH"}}``).

* **The location's granularity varies.** ``addressLocality`` is a city on some
  postings ("Pretoria") and a **province** on others ("Western Cape",
  "KwaZulu-Natal"), with ``addressRegion`` the same value. Both are in
  ``ref.cities`` / ``ref.regions`` for South Africa, so both resolve.

* **The card's date is "DD Month YYYY"** ("04 September 2026") and may carry a
  non-breaking space, so the parse normalises ``\\xa0`` before splitting.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobMailSettings(BaseSettings):
    """Configuration for the JobMail board (South Africa)."""

    model_config = SettingsConfigDict(env_prefix="JOBMAIL_", extra="ignore")

    base_url: str = Field(default="https://www.jobmail.co.za")
    listing_path: str = Field(default="/jobs/")

    page_size: int = Field(default=20, ge=1, le=100, description="Postings per listing page.")
    max_list_pages: int = Field(default=12, ge=1, le=200, description="Listing pages to walk.")
    max_jobs_per_run: int = Field(
        default=200,
        ge=1,
        description=(
            "Cap on postings fetched in one run. Measured 2026-10-20: a posting "
            "costs about 1.9s with the inter-request delay, so 200 postings is "
            "about 7 minutes -- comfortably inside a 60-minute step, and the "
            "board holds at least 8,000. The CI scrape step passes no row cap of "
            "its own, so this default IS the cap a CI run gets."
        ),
    )
    max_details_per_run: int = Field(
        default=0, ge=0, description="Cap on detail requests; 0 means max_jobs_per_run."
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)", description="Identifying UA."
    )
    timeout_seconds: int = Field(default=60, ge=1)
    inter_request_delay_seconds: float = Field(
        default=2.0,
        ge=0.0,
        description=(
            "Pause between requests. Two seconds, not one.\n\n"
            "Measured 2026-10-20: at one second the board stopped answering "
            "altogether partway through a long session -- connect timeouts on every "
            "request, on the listing and the detail pages alike -- and kept "
            "refusing for a while afterwards. Nothing in the response said so; the "
            "connection simply stopped being accepted.\n\n"
            "The board is a job aggregator and a busy one, and one request at a "
            "time with a pause is both politer and the difference between a run "
            "that completes and one that is cut off. The same reasoning the "
            "jobbank scraper records: a federal service throttles the unkind."
        ),
    )
    retry_attempts: int = Field(default=3, ge=1, le=6)
    retry_backoff_seconds: float = Field(default=6.0, ge=0.0)
