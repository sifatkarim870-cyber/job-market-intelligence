"""ANPE Mali ("Agence Nationale Pour l'Emploi") scraper.

Fetches job listings from Mali's national employment agency at
``anpe-mali.org``, whose public site is a WordPress install running the WP
Job Manager plugin with a keyless REST API. The old ``anpe.ml`` domain the
2026-10-04 sweep recorded no longer resolves; ``anpe-mali.org`` is the
live replacement.

Discovery is one readable endpoint (confirmed live 2026-11-21):

* **Listings** - ``GET https://anpe-mali.org/wp-json/wp/v2/job-listings``
  with ``per_page=100&page=N`` returns the board as a JSON array
  (``X-WP-Total: 15``, one page). ``_embed=wp:featuredmedia`` folds the
  company logo into each row, so no per-listing detail call is needed.
  Each row is a full notice: title, HTML body, publication date, public
  link, employer (``meta._company_name``) and a free-text location
  (``meta._job_location``).

``robots.txt`` is readable and permissive for this scraper (``User-agent:
*`` / ``Disallow: /wp-admin/`` / ``Allow: /wp-admin/admin-ajax.php``); the
``/wp-json/`` path used here is not disallowed. No key, no registration,
no proxy, no browser; TLS verification stays on.

Typical usage:

    from job_market_intel.scrapers.anpe_mali import (
        AnpeMaliClient, AnpeMaliParser, AnpeMaliSettings,
    )

    settings = AnpeMaliSettings()
    client = AnpeMaliClient(settings=settings)
    parser = AnpeMaliParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import AnpeMaliClient
from .config import AnpeMaliSettings
from .exceptions import (
    AnpeMaliError,
    AnpeMaliFetchError,
    AnpeMaliResponseError,
)
from .models import RawAnpeMaliJob
from .parser import AnpeMaliParser
from .pipeline import AnpeMaliPipeline, AnpeMaliPipelineRunResult

__all__ = [
    "AnpeMaliClient",
    "AnpeMaliSettings",
    "AnpeMaliError",
    "AnpeMaliFetchError",
    "AnpeMaliResponseError",
    "RawAnpeMaliJob",
    "AnpeMaliParser",
    "AnpeMaliPipeline",
    "AnpeMaliPipelineRunResult",
]
