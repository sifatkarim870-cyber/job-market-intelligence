"""Configuration for the Job Bank Canada scraper.

Job Bank is the Canadian Government's official job board
(``https://www.jobbank.gc.ca``), operated by the Government of Canada rather
than a commercial ATS. That matters twice over: it publishes under an open
government licence, and its robots.txt permits the job paths -- no proxy, no
API key, no captcha.

Why it earns a scraper here: Canada is a G2 market and was carrying 371 rows
(0.3%) in the corpus, while Iran carried 68%. It is also one of very few
large national boards that is reachable with a plain HTTP client.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobBankSettings(BaseSettings):
    """Configuration for the Job Bank Canada board scraper."""

    model_config = SettingsConfigDict(env_prefix="JOBBANK_", extra="ignore")

    base_url: str = Field(
        default="https://www.jobbank.gc.ca",
        description="Job Bank Canada root.",
    )
    search_path: str = Field(
        default="/jobsearch/jobsearch",
        description="Search endpoint. Paginated with ?term=&page=&sort=.",
    )
    posting_path: str = Field(
        default="/jobsearch/jobposting",
        description="Detail endpoint; the posting id is appended.",
    )

    #: Occupational search terms. Job Bank has no "browse everything" feed, so
    #: coverage comes from walking a term list the same way the Reed scraper
    #: walks ops.reed_search_queue. Ordered so the highest-volume occupations
    #: (which dominate any Canadian posting census) are reached first if the
    #: per-run cap bites.
    default_search_terms: list[str] = Field(
        default_factory=lambda: [
            "developer",
            "software",
            "engineer",
            "nurse",
            "teacher",
            "accountant",
            "manager",
            "administrative",
            "driver",
            "technician",
            "analyst",
            "consultant",
            "sales",
            "customer service",
            "warehouse",
            "chef",
            "carpenter",
            "electrician",
            "welder",
            "receptionist",
            "human resources",
            "finance",
            "marketing",
            "project manager",
            "data analyst",
            "security",
            "maintenance",
            "cook",
            "cashier",
        ],
        description="Occupational terms to walk. One HTTP request per term per page.",
    )

    results_per_page: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Job Bank returns 25 postings per search page by default.",
    )

    max_pages_per_term: int = Field(
        default=1,
        ge=1,
        le=25,
        description=(
            "Pages to walk per search term. Job Bank paginates with ?page=N.\n\n"
            "One page per term, not two. This is the setting that actually "
            "bounds a CI run, and it was measured rather than guessed: the "
            "detail pages dominate the cost (one request per posting), and "
            "over CI's WAN a posting costs about 60s against 7s locally -- "
            "roughly 9x. Two pages per term is ~50 postings, which is ~50 "
            "minutes of work, and that landed exactly on jobbank's 45-minute "
            "step cap: the full sweep of 2026-10-19 failed on jobbank and "
            "nothing else, with \"The action 'Run jobbank scraper' has "
            'timed out after 45 minutes".\n\n'
            "One page per term is ~25 postings, about 25 minutes, which fits "
            "inside the cap with room to spare. The registry's timeout for "
            "this source was raised 45 -> 75 minutes at the same time, so the "
            "run has headroom either way.\n\n"
            "Raise this for a local backfill with JOBBANK_MAX_PAGES_PER_TERM, "
            "where the 9x WAN penalty does not apply."
        ),
    )

    fetch_detail_pages: bool = Field(
        default=True,
        description=(
            "Search results carry a title, an employer and a date but no body "
            "text, so the description -- which is what the corpus is actually "
            "for -- only exists on the detail page."
        ),
    )

    request_timeout_seconds: int = Field(default=30, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=1.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=8.0, ge=0.0)

    inter_page_delay_seconds: float = Field(
        default=0.6,
        ge=0.0,
        description=(
            "Pause between requests. Job Bank is a federal government service; "
            "one request at a time with a pause is both politer and less "
            "likely to draw a throttle."
        ),
    )

    max_jobs_per_run: int = Field(
        default=25,
        ge=1,
        description=(
            "Cap on postings fetched in one run. Detail pages dominate the "
            "cost -- one request per posting -- so this is what actually "
            "bounds run time.\n\n"
            "25, not 1000, and the reason is that this default IS the cap a CI "
            "run gets: the workflow's scrape step passes no row cap of its own "
            "unless its max_jobs input is set, so the scraper's own default "
            "applies. Measured 2026-10-19: a posting costs about 60 seconds "
            "over CI's WAN against 7 seconds locally -- roughly 9x -- and this "
            "source has 29 search terms, so a 1000-posting budget is 29 terms "
            "of listing pages followed by hundreds of detail requests. The "
            "step was killed at its timeout with the postings fetched but "
            "**not yet persisted**, so the run wrote NOTHING. That is why "
            "Canada's jobbank rows were 40 while the budget said 1000.\n\n"
            "25 postings is about 25 minutes of fetching, which fits inside "
            "the step cap with room to spare, and the run reaches the "
            "persist step. Raise it via JOBBANK_MAX_JOBS_PER_RUN for a local "
            "backfill, where the 9x WAN penalty does not apply."
        ),
    )

    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    )
    accept_language: str = Field(
        default="en-CA,en;q=0.9",
        description="Canadian federal content is bilingual; without this some pages return French.",
    )
