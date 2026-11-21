"""ANPE Burkina Faso (ABPE) scraper configuration.

Same role as every other source's ``config.py``: values loaded through
``pydantic-settings`` so a URL, category or window change is a one-line
``.env`` edit (prefix ``ANPE_BF_``), not a code change.

The source (``www.anpe.gov.bf``, Burkina Faso's national employment
agency, rebranded "Agence Burkinabè Pour l'Emploi - Faso Tonlo Zi") is a
WordPress site whose public REST API is keyless and readable:

* ``GET /wp-json/wp/v2/posts?categories=77&per_page=100&page=N`` returns
  the category's posts as a JSON array; ``X-WP-Total`` reported 97 rows at
  scoping (2026-11-21), oldest 2024-09-13, newest 2026-07-03, so the whole
  category fits on one 100-row page.
* Category ``77`` is the site's own slug ``offres-demplois``
  ("Offres d'emplois"), the only category carrying recruitment notices;
  ``54`` is general news ("Actualite") and is deliberately excluded.
* The post object carries ``{id, date, modified, link, title.rendered,
  content.rendered, excerpt.rendered}``. The full body is HTML; there is
  no structured salary, company, location or contract field.

robots.txt posture
------------------
``https://www.anpe.gov.bf/robots.txt`` is readable (HTTP 200) and
permissive: ``User-agent: *`` / ``Allow: /`` with no ``Disallow`` lines at
all. The host is just slow and intermittently drops connections, so the
client retries transient failures instead of treating them as a verdict.

Data facts that shaped these defaults (measured 2026-11-21):

* **No salary is ever stated.** Scanning all 97 bodies found "francs
  CFA"/"F CFA" only in passphrase/stamp-fee instructions ("une demande
  manuscrite timbree a 200 F CFA") and exactly one occurrence of
  "salaire", so the cleaner never fabricates a bound; currency is XOF and
  no pay period is claimed.
* **Location is free text**, mostly "commune de <name>" (50 of 97
  bodies), "province du <name>" or "region de <name>"; the cleaner lifts
  the first commune/mairie/province/region phrase and leaves the rest to
  the shared resolver.
* **Contract type is prose**, with "CDI"/"CDD" present in 13 of 97
  bodies; the cleaner maps the words it recognises and leaves the rest
  unset.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnpeBfSettings(BaseSettings):
    """Configuration for the ANPE Burkina Faso scraper, from env/.env.

    Attributes:
        base_url: Public site base (the only host that answers; the apex
            redirects here and the old ``anpe.bf`` domain no longer
            resolves).
        posts_url: The keyless WordPress REST posts endpoint.
        category_id: The site's ``offres-demplois`` category id (77).
        per_page: Rows per page; WordPress caps this at 100.
        max_pages: Safety ceiling on pages walked per run.
        max_jobs_per_run: Safety cap on posts kept per run.
        fetch_delay_seconds: Politeness pause between page GETs.
        request_timeout_seconds: Read timeout for one page. The host can
            take tens of seconds to answer, so this is deliberately
            generous.
        max_retry_attempts: Total attempts (including the first) before a
            transient failure is fatal.
        retry_initial_wait_seconds: Wait before the first retry.
        retry_max_wait_seconds: Ceiling on exponential backoff.
        user_agent: Browser-style User-Agent; the REST API serves fine to
            one, and identifying honestly is polite regardless.
    """

    model_config = SettingsConfigDict(
        env_prefix="ANPE_BF_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_url: str = "https://www.anpe.gov.bf"
    posts_url: str = "https://www.anpe.gov.bf/wp-json/wp/v2/posts"
    category_id: int = Field(default=77, ge=1)
    per_page: int = Field(default=100, ge=1, le=100)
    max_pages: int = Field(default=5, ge=1)
    max_jobs_per_run: int = Field(default=200, ge=1)
    fetch_delay_seconds: float = Field(default=1.0, ge=0.0)
    request_timeout_seconds: float = 90.0
    max_retry_attempts: int = 4
    retry_initial_wait_seconds: float = 2.0
    retry_max_wait_seconds: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
