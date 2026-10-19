"""Configuration for the Forasna scraper (Egypt).

Measured on the live site on 2026-10-19, not assumed:

* **No browser, no key, no proxy.** Plain ``requests`` serves both the listing
  and the detail page, and robots.txt carries no ``Disallow`` at all.

* **The listing is the site's own search page**, ``/وظائف-خالية``
  ("search for jobs"), paginated with an **offset**:

      /وظائف-خالية?start=0    -> 20 postings
      /وظائف-خالية?start=20   -> 20 different postings
      /وظائف-خالية?start=2840 -> the last page

  The board reports **2,852 postings** ("2852 وظيفة").

* **The nominal all-jobs route is not usable.** ``/a/وظائف-مصر`` ("jobs in all
  fields") returns HTTP 200 and 281 KB -- with **zero** job links and no
  pagination. Only the *field* pages (``/a/<field>-في-مصر``), the *city*
  pages (``/a/وظائف-<city>``) and the search page carry a listing. The search
  page is the one used here, because it is the only one that is a single
  ordered stream rather than an overlapping set of categories.

* **The job id is the trailing number of the URL slug** --
  ``/job/p/<arabic-slug>-444468`` -- and the JSON-LD ``identifier.value``
  agrees. The ids are **not** dense: 2,000 consecutive postings span
  303,860 to 444,468, so enumerating ids is not an option and pagination is
  the only way in.

* **The detail page carries a schema.org ``JobPosting``** with everything
  needed, measured over 60 postings::

      title, identifier, datePosted, validThrough, employmentType,
      hiringOrganization.name, jobLocation.address.{addressLocality,
      addressRegion, addressCountry}

  ``baseSalary`` is present on **19 of 60** (32%) and ``description`` on
  **44 of 60** (73%).

* **The currency is per-posting, not per-board.** 18 of the sampled postings
  declare ``EGP`` and one declares **``USD``** -- an Egyptian board with a
  dollar-denominated ad. So the currency is read per record and never assumed.

* **``addressRegion`` can name a governorate of another country.** One sampled
  posting has ``addressRegion`` "أبها" -- Abha, in **Saudi Arabia** -- so the
  country comes from ``addressCountry`` and the region is not evidence of it.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ForasnaSettings(BaseSettings):
    """Configuration for the Forasna board (Egypt)."""

    model_config = SettingsConfigDict(env_prefix="FORASNA_", extra="ignore")

    base_url: str = Field(default="https://forasna.com")
    #: The site's own search page -- "وظائف خالية". The nominal all-jobs
    #: route ``/a/وظائف-مصر`` returns a page with no job links on it, so it
    #: is not used.
    listing_path: str = Field(default="/وظائف-خالية")
    detail_path: str = Field(default="/job/p")

    #: The listing pages 20 postings a page and pages by offset.
    page_size: int = Field(default=20, ge=1, le=100, description="Postings per listing page.")
    max_list_pages: int = Field(default=10, ge=1, le=200, description="Listing pages to walk.")
    max_jobs_per_run: int = Field(default=60, ge=1, description="Cap on postings this run.")
    max_details_per_run: int = Field(
        default=0, ge=0, description="Cap on detail requests; 0 means max_jobs_per_run."
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)", description="Identifying UA."
    )
    timeout_seconds: int = Field(default=60, ge=1)
    inter_request_delay_seconds: float = Field(default=1.0, ge=0.0)
    retry_attempts: int = Field(default=3, ge=1, le=6)
    retry_backoff_seconds: float = Field(default=6.0, ge=0.0)
