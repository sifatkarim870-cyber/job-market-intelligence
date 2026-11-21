"""BongThom (bongthom.com) scraper configuration.

Same role as every other source's ``config.py``: values loaded via
``pydantic-settings`` so a URL or window change is a one-line ``.env``
edit (prefix ``BONGTHOM_COM_``), not a code change.

What BongThom is
----------------
BongThom (``https://bongthom.com``) is one of Cambodia's largest job
boards. Its public site is a Laravel application whose front end is backed
by plain ``*_Controller`` JSON routes, all keyless, plus a server-rendered
detail page. The workbook's recorded domain for this row is
``bongthom.com``.

Where the data lives (confirmed live, 2026-11-21)
-------------------------------------------------
* **Discovery** -- ``GET
  https://bongthom.com/Job_Controller/get_all?page=N`` returns the board's
  own Laravel paginator envelope
  (``{current_page, data[], last_page, per_page, total, ...}``); ``data``
  rows are the newest-first feed and ``per_page`` is fixed at 40 (the
  ``per_page``/``limit`` query params are ignored). The whole board was
  **278 jobs over 7 pages** at scoping.
* **Structured detail** -- ``GET
  https://bongthom.com/Job_Controller/get_embed/<id>`` returns the full
  posting as JSON: ``positions[]`` each carrying an HTML ``description``,
  ``duties[].text``, ``benefits[].benefit``, ``skill_knowledges[].skill``,
  ``categories[].name_en``, ``qualifications[].major`` and
  ``experiences[]`` with numeric ``years``. It is keyless and needs no
  cookie.
* **Rendered detail** -- ``GET
  https://bongthom.com/job_detail/view_detail_<id>.html`` is the
  server-rendered posting page. Its "Workplace Circumstances" list is the
  only place the *displayed* work location, salary and schedule appear:
  ``get_embed`` leaves ``schedule``/``salary`` null for most rows and its
  ``locations`` objects are legacy office addresses, not the work site.

Fetching therefore uses that split: discovery, then two keyless GETs per
job (the structured embed plus the rendered page). No key, no
registration, no login, no proxy and no browser.

robots.txt posture
------------------
``https://bongthom.com/robots.txt`` (and the ``www.``/``front.`` hosts)
answer HTTP 200 with the application's HTML marketing page under
``text/html`` rather than a ``text/plain`` policy file -- there is no
robots policy to obey, the same "app shell instead of a policy file"
posture ``llv_li`` documented. ``account.bongthom.com/robots.txt`` is an
independent 404. Nothing here is disallowed; the scraper only reads the
three public routes above.

Data facts that shaped these defaults (measured 2026-11-21):

* **Salary is a ``$`` figure.** Disclosed rows read ``$<min> - $<max>`` or
  a single ``$<value>``; the rest say "Negotiable", "Based on Experience",
  "N/A", "Other Benefits" or a combination. Currency is ``USD`` (Cambodia's
  dollarised economy) and pay is quoted monthly.
* **Schedule is prose.** "Full-time", "Part-time", "Short-term" or a
  combination; the cleaner maps the recognized single labels onto
  ``ref.employment_types``.
* **Experience is numeric.** ``experiences[].years`` holds whole years; the
  cleaner keeps the minimum across a posting's positions.
* **Every posting is Cambodian in practice.** The work location names a
  province ("Phnom Penh", "Siemreap Province"), a home-working label or,
  rarely, a neighbour ("Laos"), never a country; see
  ``normalization/geographic_resolution.py`` (``SOURCE_HOME_COUNTRY``).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BongthomSettings(BaseSettings):
    """Configuration for the BongThom scraper, loaded from environment/.env.

    Attributes:
        list_url: The paginated newest-first job feed.
        embed_url: Structured detail prefix; the full URL is
            ``embed_url + <id>``.
        detail_page_base: Rendered detail prefix; the full URL is
            ``detail_page_base + <id> + ".html"`` and that same URL is the
            stored ``original_url``.
        web_base_url: Public site base, used only to make logs readable.
        max_jobs_per_run: Safety cap on jobs kept per run (the board held
            278 at scoping).
        max_pages: Safety cap on discovery pages walked, independent of the
            run cap.
        fetch_delay_seconds: Polite pause between requests.
        request_timeout_seconds: Max time to wait for one GET.
        max_retry_attempts: Total attempts (including the first) before
            giving up on a transient failure.
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff.
        user_agent: Browser-style User-Agent; the site serves fine to one,
            and identifying honestly is polite regardless.
    """

    model_config = SettingsConfigDict(
        env_prefix="BONGTHOM_COM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    list_url: str = "https://bongthom.com/Job_Controller/get_all"
    embed_url: str = "https://bongthom.com/Job_Controller/get_embed/"
    detail_page_base: str = "https://bongthom.com/job_detail/view_detail_"
    web_base_url: str = "https://bongthom.com"
    max_jobs_per_run: int = Field(default=300, ge=1)
    max_pages: int = Field(default=50, ge=1)
    fetch_delay_seconds: float = Field(default=0.3, ge=0.0)
    request_timeout_seconds: float = 60.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 1.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def detail_url(self, job_id: str) -> str:
        """Public rendered detail page URL for ``job_id``."""
        return f"{self.detail_page_base}{job_id}.html"

    def embed_detail_url(self, job_id: str) -> str:
        """Structured JSON detail URL for ``job_id``."""
        return f"{self.embed_url}{job_id}"
