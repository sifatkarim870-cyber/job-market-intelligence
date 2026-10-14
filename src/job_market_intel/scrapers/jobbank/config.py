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
        default=2,
        ge=1,
        le=25,
        description=(
            "Pages to walk per search term. Job Bank paginates with ?page=N; two "
            "pages per term is ~50 postings before the per-run job cap applies."
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
        default=1000,
        ge=1,
        description=(
            "Cap on postings persisted in one run. Detail pages dominate the "
            "cost -- one request per posting -- so this is what actually bounds "
            "run time. Raise it via JOBBANK_MAX_JOBS_PER_RUN for a local "
            "backfill."
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
