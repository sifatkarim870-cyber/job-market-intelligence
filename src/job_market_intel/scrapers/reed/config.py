"""Reed-specific configuration.

Mirrors ``scrapers/remoteok/config.py``/``scrapers/remotive/config.py``'s
reasoning: these values live here, loaded via ``pydantic-settings``, so a
change to a URL or a timeout tweak is a one-line ``.env`` edit, not a code
change. Add entries prefixed with ``REED_`` to your ``.env`` file to
override a default — for example::

    REED_API_KEY=your-real-key-here
    REED_MAX_JOBS_PROCESSED_PER_RUN=100

Genuinely different from every other source's config, and why
-------------------------------------------------------------
``api_key`` has NO default and is required — unlike every field on every
other source's settings class. RemoteOK and Remotive need no
authentication at all; Reed requires HTTP Basic Auth (the API key as
username, blank password) on every single request (confirmed live against
``reed.co.uk/developers/jobseeker`` and against real API responses during
scoping). Constructing ``ReedSettings()`` with no ``REED_API_KEY`` set
raises immediately, by design — a scraper silently making unauthenticated
requests that all fail with 401 is a worse failure mode than refusing to
start.

``results_per_page``, ``max_search_pages_per_query``, and
``max_jobs_processed_per_run`` exist because Reed, unlike RemoteOK/
Remotive's single unpaginated feed, is a two-endpoint, paginated API:
    - Search returns at most 100 results per call (confirmed: Reed's own
      docs state ``resultsToTake`` defaults to, and is capped at, 100),
      paged via ``resultsToSkip``. ``results_per_page`` is that 100,
      pulled into a named setting rather than a magic number.
    - Reed does not publish a total-results ceiling anywhere (confirmed:
      no such figure appears on their developer docs page), but a
      commonly-reported real-world figure is ~1,000 total results per
      query — unverified against Reed itself, so ``max_search_pages_per_query``
      exists as a configurable safety cap (default 10 pages = 1,000
      results) rather than looping until Search returns an empty page,
      which could run away if that reported ceiling turns out to be
      wrong.
    - Search alone does not reliably return ``currency``/``salaryType``/
      ``contractType`` at all — confirmed live: real Search responses
      returned ``"currency": null`` even for jobs whose Details response
      had real currency/salary-type data. Getting the per-record pay
      period this scraper exists to capture correctly requires a second,
      per-job Details call (see ``client.py``'s module docstring) — an
      N+1 pattern with a real, uncapped-by-Reed cost. No documented daily
      request ceiling exists (the only figure found during scoping was a
      single third-party directory's unverified "1000 requests/day"
      claim, not confirmed by Reed itself or by any response header).
      ``max_jobs_processed_per_run`` is a conservative, explicit, tunable
      ceiling on how many jobs (each costing exactly one Details call)
      one pipeline run will process — see ``pipeline.py``'s module
      docstring for why jobs beyond this cap are deferred to a future run
      entirely, rather than processed with a skipped Details call: the
      latter would risk silently storing stale currency/pay_period/
      employment_type data for a job whose title or salary changed since
      last scraped but whose Details refresh got skipped for budget
      reasons. Deliberately conservative until real production behavior
      (429s, or the lack of them) has been observed and this can be
      raised with actual evidence behind it, not a guess.

      One real data point exists as of 2026-09-27: a live dry run
      processed 200 jobs (10 Search pages + 200 Details calls = 210
      total requests) in ~142 seconds with zero 429s or failures of any
      kind. That's evidence the current default has real headroom, not
      confirmation of any actual ceiling — still no official number
      published anywhere, and this was one run, not sustained/scheduled
      load. Raise ``max_jobs_processed_per_run`` incrementally with more
      observed runs, not in one jump based on this alone.

``queries_claimed_per_run`` exists for a different, related reason: once
"what to search for" moved from one hardcoded placeholder query
(``scrapers/reed/search_queries.py``) to a persistent, growing queue
(``ops.reed_search_queue`` — see that migration's own module docstring),
one run needs its own cap on how many (keywords, location) combinations
to claim and search, separate from ``max_jobs_processed_per_run``'s cap
on individual job postings. The two compose: claimed queries -> Search
(up to ``max_search_pages_per_query`` pages each) -> results aggregated ->
capped at ``max_jobs_processed_per_run`` for Details-fetching. Default of
5 is a project-owner-delegated choice (2026-09-27 scoping conversation),
deliberately conservative for the same reason ``max_jobs_processed_per_run``
is: 5 claimed queries x up to 10 Search pages each is up to 50 additional
Search-endpoint requests per run on top of whatever Details calls follow,
and there is still no confirmed daily ceiling to plan against.
    """

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ReedSettings(BaseSettings):
    """Configuration for the Reed scraper, loaded from environment/.env.

    Attributes:
        api_key: Reed Jobseeker API key, registered free at
            reed.co.uk/developers/jobseeker. Required — see the module
            docstring for why this has no default. Sent as the HTTP Basic
            Auth username on every request, with an empty password
            (Reed's documented auth scheme).
        search_url: Reed's job search endpoint.
        details_url: Reed's single-job details endpoint. The specific
            job ID is appended as a path segment by ``client.py``
            (``f"{details_url}/{job_id}"``), not templated here.
        results_per_page: Passed as Search's ``resultsToTake`` parameter.
            100 is both the default AND the documented maximum Reed
            accepts — see the module docstring.
        max_search_pages_per_query: Safety cap on how many Search pages
            (via ``resultsToSkip``) one query will page through before
            stopping, regardless of whether Reed reports more results
            available. See the module docstring for why this exists
            rather than looping to exhaustion.
        max_jobs_processed_per_run: Safety cap, across every query in one
            run combined, on how many jobs get a Details call (and are
            therefore cleaned/stored) in one pipeline run. See the module
            docstring and ``pipeline.py``.
        queries_claimed_per_run: How many ``ops.reed_search_queue`` rows
            one pipeline invocation claims and searches per run. See the
            module docstring for the full reasoning and how this composes
            with ``max_jobs_processed_per_run``.
        request_timeout_seconds: Max time to wait for Reed to respond to
            a single request (Search page or Details lookup) before
            treating it as failed.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure for a single request.
        retry_initial_wait_seconds: How long to wait before the first
            retry after a transient failure.
        retry_max_wait_seconds: Ceiling on the exponential backoff wait
            time between retries. Also the effective cooldown applied
            when Reed returns 429 (rate limited) — see
            ``common/http_client.py``'s ``fetch_json`` for how 429 is
            classified as retryable.
        user_agent: Identifying User-Agent string sent with every
            request.
    """

    model_config = SettingsConfigDict(
        env_prefix="REED_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str
    search_url: str = "https://www.reed.co.uk/api/1.0/search"
    details_url: str = "https://www.reed.co.uk/api/1.0/jobs"
    results_per_page: int = Field(default=100, ge=1, le=100)
    max_search_pages_per_query: int = Field(default=10, ge=1)
    max_jobs_processed_per_run: int = Field(default=200, ge=0)
    queries_claimed_per_run: int = Field(default=5, ge=0)
    request_timeout_seconds: float = 15.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "JobMarketIntelligencePlatform-Research/1.0 (+https://example-research-project.local)"
    )
