"""Configuration for the USAJOBS scraper (US federal government).

Verified against the live API on 2026-10-14 with a real key:

  * Search is ``GET /api/search`` with ``ResultsPerPage`` (max 500) and ``Page``
    (max to 10,000 records). The response nests results under
    ``SearchResult.SearchResultItems``, and each item wraps the posting in
    ``MatchedObjectDescriptor`` with ``MatchedObjectId`` and ``RelevanceRank``
    alongside -- that envelope did not exist in the older v1 shape.
  * There is **no position detail endpoint**. ``/api/v2/position/{id}``,
    ``/api/position/{PositionID}`` and three other spellings all return 404,
    whether given the PositionID or the numeric id from PositionURI.
  * The full job description therefore comes from the public job page at
    ``PositionURI``, which carries a schema.org ``JobPosting`` JSON-LD block.
    Its field names share nothing with the API's: the page has
    ``description``/``qualifications``/``baseSalary`` while the API has
    ``PositionTitle``/``QualificationSummary``/``PositionRemuneration``. Both
    are used, because each holds something the other lacks.

The key is a US federal data.gov key from
https://developer.usajobs.gov/. It is read from ``USAJOBS_API_KEY`` or
``USAJOBS_API_KEY_FILE`` and is never committed.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class USAJobsSettings(BaseSettings):
    """Configuration for the USAJOBS federal job board."""

    model_config = SettingsConfigDict(env_prefix="USAJOBS_", extra="ignore")

    api_base_url: str = Field(
        default="https://data.usajobs.gov/api",
        description="USAJOBS API root.",
    )
    search_path: str = Field(default="/search", description="Search endpoint.")

    api_key: str | None = Field(
        default=None,
        description=(
            "data.gov Authorization-Key. Read from USAJOBS_API_KEY, or from the "
            "file named by USAJOBS_API_KEY_FILE. Never commit either."
        ),
    )
    api_key_file: Path | None = Field(
        default=None,
        description="Path to a file holding the key (useful locally, via .env).",
    )
    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description=(
            "data.gov requires a User-Agent identifying the caller; a bare "
            "browser string is rejected."
        ),
    )

    #: Keywords to walk. USAJOBS has no browse-all feed, so coverage comes from
    #: a keyword list the way Reed's ops.reed_search_queue works. Broad and
    #: common terms first, because they return the most distinct postings.
    default_keywords: list[str] = Field(
        default_factory=lambda: [
            "engineer",
            "IT",
            "analyst",
            "nurse",
            "physician",
            "teacher",
            "manager",
            "administrative",
            "technician",
            "accountant",
            "lawyer",
            "specialist",
            "security",
            "driver",
            "maintenance",
            "scientist",
            "research",
            "program",
            "clerk",
            "inspector",
            "attorney",
            "social worker",
            "psychologist",
            "dietitian",
            "electrician",
            "welder",
            "machinist",
            "carpenter",
            "plumber",
            "HR",
            "recruiter",
            "paralegal",
            "auditor",
            "actuary",
        ],
        description="Search keywords. One API request per page per keyword.",
    )

    results_per_page: int = Field(
        default=50,
        ge=1,
        le=500,
        description="USAJOBS caps ResultsPerPage at 500.",
    )

    max_pages_per_keyword: int = Field(
        default=1,
        ge=1,
        le=20,
        description=(
            "Pages per keyword. data.gov rate-limits keys hard (500 requests "
            "per hour per key), so the default is deliberately low -- raise it "
            "only once the key's budget has been measured."
        ),
    )

    fetch_job_pages: bool = Field(
        default=True,
        description=(
            "Fetch each PositionURI for the full description. The API's own "
            "PositionFormattedDescription is a marker object, not text, and "
            "there is no detail endpoint -- so without this the corpus gets "
            "QualificationSummary only."
        ),
    )

    request_timeout_seconds: int = Field(default=45, ge=1)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: data.gov's published budget is 500 requests/hour/key. One page request
    #: plus one job page per result is ~51 requests for a 50-result page, so a
    #: 1.0s floor keeps a full keyword inside the hourly budget rather than
    #: earning a 403 halfway through.
    inter_request_delay_seconds: float = Field(default=1.0, ge=0.0)

    max_jobs_per_run: int = Field(
        default=300,
        ge=1,
        description=(
            "Cap on postings persisted in one run. Job pages dominate the "
            "request count, so this is what keeps a run inside the key's "
            "hourly budget. Raise via USAJOBS_MAX_JOBS_PER_RUN."
        ),
    )

    @model_validator(mode="after")
    def _load_key_from_file(self) -> USAJobsSettings:
        """Fall back to the key file when the variable itself is unset.

        A *model* validator rather than a field validator on purpose: pydantic
        only exposes previously-declared fields through ``info.data``, and
        ``api_key`` is declared before ``api_key_file``, so a field validator
        there cannot see the path -- it silently resolves to no key at all,
        which then surfaces as an auth error far from the real cause.

        Keeping the secret in a file rather than .env means it never lands in
        a config file that gets copied around or committed by accident.
        """
        if self.api_key:
            self.api_key = self.api_key.strip()
            return self
        path = self.api_key_file
        if path is None:
            env_path = os.environ.get("USAJOBS_API_KEY_FILE")
            path = Path(env_path) if env_path else None
        if path and Path(path).exists():
            token = Path(path).read_text(encoding="utf-8").strip()
            self.api_key = token or None
        return self
