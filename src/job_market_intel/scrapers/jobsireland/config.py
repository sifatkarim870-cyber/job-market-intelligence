"""Configuration for the JobsIreland.ie scraper (Ireland).

Measured on the live site on 2026-10-19, not assumed:

* **It is an Orchard CMS site and is server-rendered.** Both the listing and
  the detail page come back complete in a plain ``requests`` GET -- 176 KB with
  the posting cards, 97 KB with the full ad body. So this is the first source
  in a while that needs **no headless browser**: ``browser`` is absent from its
  ``config/sources.json`` entry, and CI will not install Chromium for it.

* **The listing is an HTML fragment endpoint.** ``search()`` in the page's own
  inline script calls
  ``$.ajax({url: '/Jobsireland.API/JobsIreland/BrowseJobs', ...})``, and that
  endpoint answers with ``content-type: text/html`` -- the same card markup
  without the page chrome. It is used in preference to
  ``/en-US/browse-jobs`` for one measured reason: it honours ``pageSize``
  exactly, while the full page returns ``pageSize + 1`` cards.

* **Every field is a hidden input, one set per card**, flat in document order::

      JobId         2475739
      JobReference  #CES-2475739
      CompanyLogo   (usually empty)
      JobTitle      Caretaker of Sports Ground (Elton) - CE Scheme - SLIABH RI LIMITED
      Location      Elton, Knocklong, Co. Limerick, E34 Y540
      StartDate     2026-10-19T12:05:30
      EndDate       2026-11-30T00:00:00
      VacancyTypeId 3

  So one listing request yields id, reference, title, address, published date,
  deadline and vacancy type. Only the description needs the detail page.

* **``ContractTypeId`` must be omitted.** The site's own ``searchVacancy()``
  sends ``ContractTypeId=-1`` alongside five other filters, and that combination
  returns **zero cards** on a 128 KB page -- the handler treats ``-1`` as a real
  filter value, not a wildcard. Measured: adding it alone takes the listing from
  11 cards to 0. Every filter is therefore left off the URL entirely.

* **Pagination is ``?page=N&pageSize=M``** on its own. Paging to exhaustion at
  ``pageSize=50`` reached **3,898 distinct postings** across 78 pages.

* **The transient empty board.** Partway through one 78-page walk the listing
  began returning ``0 job found`` -- with no cookies set and a clean session,
  on every parameter set, while detail pages stayed HTTP 200. It recovered on
  its own within minutes. So an empty listing is NOT proof the board is empty,
  and the client retries rather than reporting success with zero rows.

* **The detail page's metadata is self-describing via ``img.alt``.** Every ``<li>``
  in ``ul.job-detail_list`` carries an icon whose ``alt`` names the field::

      <img alt="Image for Employer">   SLIABH RI LIMITED
      <img alt="Image for Job Ref">    Ref: #CES-2475739
      <img alt="Image for Location">   Elton, Knocklong, Co. Limerick
      <img alt="Image Position">       No of positions: 1
      <img alt="Image Part Time">      Community Employment Programme
      <img alt="Image Hours per week"> 19.5 hours per week
      <img alt="Image for Euro">       Community Employment Programme Rates
      <img alt="Image for Published">  Published On: 19 Oct 2026
      <img alt="Image for Closing">    Closing On: 30 Nov 2026

  That is a far more stable handle than the site's class names, which are
  mostly absent.

* **There is no salary.** ``alt="Image for Euro"`` is the euro icon, but the
  text beside it is the *label* of a link to a programme-wide rates page --
  "Community Employment Programme Rates" -- not a figure. Reading a number out
  of it would be inventing one.

robots.txt: ``User-agent: *`` with no ``Disallow``, i.e. the whole site is
permitted. It advertises a sitemap at https://jobsireland.ie/sitemap.xml.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobsIrelandSettings(BaseSettings):
    """Configuration for the JobsIreland.ie board (Ireland)."""

    model_config = SettingsConfigDict(env_prefix="JOBSIRELAND_", extra="ignore")

    base_url: str = Field(default="https://jobsireland.ie")
    #: The HTML-fragment endpoint behind the listing's own ajax call. Used in
    #: preference to the full page because it returns exactly pageSize cards.
    list_api_path: str = Field(default="/Jobsireland.API/JobsIreland/BrowseJobs")
    #: The full listing page, kept for the discovery sanity check: if the
    #: fragment endpoint ever changes shape, the page still proves postings
    #: exist rather than the source reporting a healthy empty run.
    listing_page_path: str = Field(default="/en-US/browse-jobs")
    detail_path: str = Field(default="/en-US/job-Details")

    page_size: int = Field(
        default=50, ge=1, le=200, description="Cards per listing request. Honoured exactly."
    )
    max_list_pages: int = Field(default=20, ge=1, le=400, description="Listing pages to walk.")
    max_jobs_per_run: int = Field(default=60, ge=1, description="Cap on postings this run.")
    max_details_per_run: int = Field(
        default=0, ge=0, description="Cap on detail requests; 0 means max_jobs_per_run."
    )

    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)", description="Identifying UA."
    )
    timeout_seconds: int = Field(default=60, ge=1)
    inter_request_delay_seconds: float = Field(default=1.5, ge=0.0)
    #: An empty listing is usually transient -- the board genuinely served
    #: "0 job found" for several minutes mid-walk -- so it is retried before
    #: being believed.
    empty_listing_retries: int = Field(default=3, ge=0, le=10)
    empty_listing_backoff_seconds: float = Field(default=20.0, ge=0.0)
    retry_attempts: int = Field(default=3, ge=1, le=6)
    retry_backoff_seconds: float = Field(default=8.0, ge=0.0)
