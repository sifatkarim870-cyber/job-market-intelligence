"""Job.am-specific configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or timeout change is a one-line ``.env``
edit (prefix ``JOBAM_``), not a code change.

No API key needed (job.am's job-list JSON endpoint answers a plain GET
without auth, confirmed live 2026-10-05), so ``api_key`` does not exist
here — everything has a sensible default and the scraper works out of
the box.

One job.am-specific knob worth calling out: ``max_jobs_per_run``. Unlike
every other JSON source, job.am's endpoint is not paginated — a single
GET returns the *entire* board (~1,136 jobs, ~350 KB, confirmed live),
and pagination query parameters are silently ignored. The cap therefore
limits how many of those listed jobs get their (relatively expensive,
one-at-a-time) detail page fetched, not how many list pages are read.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JobAmSettings(BaseSettings):
    """Configuration for the Job.am scraper, loaded from environment/.env.

    Attributes:
        list_url: The job-list JSON endpoint. One GET returns the whole
            board as a bare JSON array (no envelope, no pagination —
            query parameters such as ``?page=2`` are ignored).
        max_jobs_per_run: Safety cap on how many listed jobs one run
            processes. The full board is ~1,136 listings; each one
            processed costs an extra detail-page request, so the cap
            keeps a pipeline run bounded and polite. Raise via
            ``JOBAM_MAX_JOBS_PER_RUN``.
        fetch_details: Whether to fetch each listed job's public page
            for its ``JobPosting`` JSON-LD. The list payload has no
            ``description``, no posting date, and no employment type —
            all three live only in that JSON-LD — so descriptions (skill
            extraction, word-count quality signal) and the posting date
            (a NOT NULL part of the jobs key) both depend on this step.
            Setting it to False makes jobs unparseable by design; it
            exists only for debugging the list half in isolation.
        detail_fetch_delay_seconds: Politeness pause between detail
            fetches (one run makes up to ``max_jobs_per_run`` of them).
            0 for no delay.
        request_timeout_seconds: Max time to wait for one request.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff (also the
            effective cooldown after a 429).
        impersonate: Browser TLS/HTTP2 profile used by ``curl_cffi`` for
            every request to this source (default ``"chrome"`` = the
            latest bundled Chrome profile; version-pinned values such as
            ``"chrome124"`` are also accepted by curl_cffi). This is
            what actually gets job.am past its Cloudflare managed
            challenge from CI — see ``client.py``'s module docstring for
            the three failed UA-only attempts that led here. There is
            deliberately no ``user_agent`` knob: a User-Agent override
            would desynchronize the header set from the impersonated
            TLS fingerprint, which is exactly the mismatch Cloudflare
            scores.
    """

    model_config = SettingsConfigDict(
        env_prefix="JOBAM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    list_url: str = "https://job.am/api/jobs"
    max_jobs_per_run: int = Field(default=100, ge=1)
    fetch_details: bool = True
    detail_fetch_delay_seconds: float = Field(default=0.5, ge=0.0)
    request_timeout_seconds: float = 20.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    impersonate: str = "chrome"
