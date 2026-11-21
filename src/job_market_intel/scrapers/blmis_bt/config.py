"""BLMIS (bhutan) scraper configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or window change is a one-line ``.env``
edit (prefix ``BLMIS_BT_``), not a code change.

What BLMIS is
-------------
BLMIS -- the **B**hutan **L**abour **M**arket **I**nformation **S**ystem at
``https://www.blmis.gov.bt`` -- is the job portal of Bhutan's labour
ministry (MoLHR, whose functions now sit under MOICE; the site links to
``facebook.com/moicebt`` and ``twitter.com/MOLHRBhutan``). The workbook's
recorded domain for this row, ``jobs.molhr``, no longer exists: both
``molhr.gov.bt`` and ``jobs.molhr.gov.bt`` are NXDOMAIN at the ``.bt``
authoritative nameservers. BLMIS is the successor portal, and this is a
successor build in the same spirit as ``llv_li`` (whose state vacancies
moved onto a SmartRecruiters board).

Where the data lives (confirmed live, 2026-11-21)
-------------------------------------------------
The jobseeker page ``/jobseeker_page/mispage`` ("Vacancies & Trainings")
is a Laravel **Livewire** page: the server renders the current vacancies
into the component's ``wire:initial-data`` attribute (a JSON blob) before
any JavaScript runs. Read as RFC 9309 (``docs/robots`` posture below),
that single public GET is the whole source -- no key, no login, no
cookies, no proxy, no browser, and no AJAX follow-up.

``serverMemo.data`` carries six ``job_by_*`` arrays -- ``categories``,
``location``, ``company``, ``qualification``, ``yelp`` (Youth Employment
& Livelihood Programme) and ``oversea`` -- which are overlapping browse
facets over the SAME inventory. Their union was **442 unique**
``application_no`` values at scoping (``job_by_company`` alone held 362),
so the client merges all six and de-duplicates by ``application_no``.

Each record is rich: ``designation`` (title), ``business_name`` /
``company_name`` (employer), ``job_description``, ``employment_type``
("Regular"/"Contract"), ``starting_salary`` (numeric, monthly),
``slot`` (vacancies), ``last_date_registration`` (closing date),
``created_at`` (posting date), ``dzongkhag_name``/``gewog_name``
(district/sub-district), ``qualification``, ``job_category`` and a
``vacancy_type_id`` (516 marks an overseas posting, whose destination
country sits in ``placement``).

robots.txt posture
------------------
``https://www.blmis.gov.bt/robots.txt`` (HTTP 200) is a bare
``User-agent: *`` group with an EMPTY ``Disallow`` (allow-all) and no
``Crawl-delay``. Nothing here is disallowed; the scraper makes a single
GET per run regardless.

Data facts that shaped these defaults (measured 2026-11-21):

* **Salary is a single monthly figure.** ``starting_salary`` is quoted
  once (no range); the cleaner stores it as the lower bound and leaves the
  upper bound unstated rather than inventing one. Currency is ``BTN``
  (ngultrum) by convention; the few overseas postings quote the
  destination's currency instead (see ``cleaning/blmis_bt_cleaner.py``).
* **Employment type is prose.** ``employment_type`` is "Regular" or
  "Contract"; the cleaner maps the recognized labels onto
  ``ref.employment_types``.
* **No skills or work-mode field exists**, so the cleaner leaves them
  empty/None rather than guessing.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BlmisSettings(BaseSettings):
    """Configuration for the BLMIS scraper, loaded from environment/.env.

    Attributes:
        list_url: The public jobseeker page whose ``wire:initial-data``
            carries the whole vacancy inventory.
        web_base_url: Public site base, used only to make logs readable.
        detail_page_base: Public detail page prefix; the stored
            ``original_url`` is ``detail_page_base + <application_no>``
            (a human link -- it is never fetched).
        max_jobs_per_run: Safety cap on jobs kept per run (the board held
            442 at scoping).
        request_timeout_seconds: Max time to wait for the single GET.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff.
        user_agent: Browser-style User-Agent; the page serves fine to one,
            and identifying honestly is polite regardless.
    """

    model_config = SettingsConfigDict(
        env_prefix="BLMIS_BT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    list_url: str = "https://www.blmis.gov.bt/jobseeker_page/mispage"
    web_base_url: str = "https://www.blmis.gov.bt"
    detail_page_base: str = "https://www.blmis.gov.bt/jobseeker_page/jobdetails/"
    max_jobs_per_run: int = Field(default=500, ge=1)
    request_timeout_seconds: float = 60.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
