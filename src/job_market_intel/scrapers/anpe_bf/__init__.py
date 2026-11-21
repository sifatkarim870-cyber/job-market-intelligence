"""ANPE Burkina Faso (ABPE "Faso Tonlo Zi") scraper.

Fetches recruitment notices from Burkina Faso's national employment
agency at ``www.anpe.gov.bf``, whose public site is a WordPress install
with a keyless REST API. The old ``anpe.bf`` domain no longer resolves and
the agency now brands itself "Agence Burkinabè Pour l'Emploi".

Discovery is one readable endpoint (confirmed live 2026-11-21):

* **Offers** - ``GET https://www.anpe.gov.bf/wp-json/wp/v2/posts`` with
  ``categories=77&per_page=100&page=N`` returns the ``offres-demplois``
  category as a JSON array (``X-WP-Total: 97``, one page). Each post is a
  full recruitment notice: title, HTML body, publication date and public
  link. There is no structured salary, employer, location or contract
  field, so the cleaner lifts the prose signals it can.

``robots.txt`` is readable and permissive (``User-agent: *`` /
``Allow: /``, no ``Disallow``). No key, no registration, no proxy, no
browser; TLS verification stays on.

Typical usage:

    from job_market_intel.scrapers.anpe_bf import (
        AnpeBfClient, AnpeBfParser, AnpeBfSettings,
    )

    settings = AnpeBfSettings()
    client = AnpeBfClient(settings=settings)
    parser = AnpeBfParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import AnpeBfClient
from .config import AnpeBfSettings
from .exceptions import (
    AnpeBfError,
    AnpeBfFetchError,
    AnpeBfResponseError,
)
from .models import RawAnpeBfJob
from .parser import AnpeBfParser
from .pipeline import AnpeBfPipeline, AnpeBfPipelineRunResult

__all__ = [
    "AnpeBfClient",
    "AnpeBfSettings",
    "AnpeBfError",
    "AnpeBfFetchError",
    "AnpeBfResponseError",
    "RawAnpeBfJob",
    "AnpeBfParser",
    "AnpeBfPipeline",
    "AnpeBfPipelineRunResult",
]
