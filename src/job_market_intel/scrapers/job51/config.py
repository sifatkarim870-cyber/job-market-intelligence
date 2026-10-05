"""51job-specific configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or cap change is a one-line ``.env`` edit
(prefix ``JOB51_``), not a code change.

No API key and no signing needed: the PC search endpoint
(``cupid.51job.com/pc/open/noauth/search-h5``) answers a plain GET
without auth, cookies, or the ``sign`` header its own JS bundle computes
(verified live during scoping, 2026-10-05 — see ``client.py``'s module
docstring), so ``api_key`` does not exist here and the scraper works out
of the box.

Knobs worth calling out:

* ``keyword`` — the board's general feed needs none (an omitted keyword
  returns the default mixed listing, 1,000-item window). Set one to
  target a query instead (e.g. ``JOB51_KEYWORD=python``).
* ``max_jobs_per_run`` — one response carries up to ``page_size`` jobs
  *complete with description, salary, and posting date* (no per-job
  detail fetch, unlike Job.am), so this cap is cheap to raise: 300 is
  three requests per run.
* ``page_size`` — the API served 100 items/page during scoping (its own
  web UI also asks for 100); the server is the authority on what it
  accepts, hence the ``le=100`` ceiling here rather than a guess.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Browser-shaped UA accepted by the endpoint during scoping. A knob
#: (like RemoteOK's) rather than a fixed value: the API answers a plain
#: ``requests`` call, so unlike Job.am's curl_cffi case there is no
#: TLS-fingerprint contract to keep in sync with a header override.
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class Job51Settings(BaseSettings):
    """Configuration for the 51job scraper, loaded from environment/.env.

    Attributes:
        search_url: The undocumented PC search endpoint. GET with
            ``pageNum``/``pageSize``(/``keyword``) query params returns
            JSON (``status == "1"`` → ``resultbody.job.items[]``).
        keyword: Optional search keyword; ``None`` (default) fetches the
            board's general feed. Empty string is treated as absent.
        page_size: Items per request (1–100; 100 confirmed live).
        max_jobs_per_run: Safety cap on how many jobs one run processes
            (deduplicated by ``jobId`` before the cap is applied).
        page_fetch_delay_seconds: Politeness pause between page requests.
        request_timeout_seconds: Max time to wait for one request. 45s:
            responses are ~500 KB of JSON and one read timed out at 25s
            during scoping (2026-10-05) — the retry layer handles the
            rest.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure (timeout, 429, 5xx).
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff.
        user_agent: User-Agent sent with every request.
    """

    model_config = SettingsConfigDict(
        env_prefix="JOB51_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    search_url: str = "https://cupid.51job.com/pc/open/noauth/search-h5"
    keyword: str | None = None
    page_size: int = Field(default=100, ge=1, le=100)
    max_jobs_per_run: int = Field(default=300, ge=1)
    page_fetch_delay_seconds: float = Field(default=0.5, ge=0.0)
    request_timeout_seconds: float = 45.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = _DEFAULT_USER_AGENT
