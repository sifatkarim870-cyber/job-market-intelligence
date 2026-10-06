"""HR.ge scraper.

Fetches job listings from HR.ge (https://www.hr.ge), Georgia's largest
job board, validated into typed ``RawHRGeJob`` objects.

HR.ge publishes no documented API, but its Angular frontend talks to a
plain JSON API at ``api.p.hr.ge/public-portal/tenant/1/api/v3/`` (list
via ``POST announcement-search``, details via ``GET announcement/{id}``)
— both unauthenticated, confirmed live during scoping (2026-10-06/07).
The scraper pages through the list (~3,596 active vacancies, 100 per
page), merges each job's detail payload (the only place ``description``
and taxonomy live), and returns typed objects. Requests ask for English
(``Accept-Language: en``) so titles/taxonomy/cities arrive in English;
Georgian leftovers are handled by the translation layer.

Typical usage:

    from job_market_intel.scrapers.hrge import HRGeClient, HRGeParser, HRGeSettings

    settings = HRGeSettings()
    client = HRGeClient(settings=settings)
    parser = HRGeParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import HRGeClient
from .config import HRGeSettings
from .exceptions import HRGeError, HRGeFetchError, HRGeResponseError
from .models import RawHRGeJob
from .parser import HRGeParser
from .pipeline import HRGePipeline, HRGePipelineRunResult

__all__ = [
    "HRGeClient",
    "HRGeSettings",
    "HRGeError",
    "HRGeFetchError",
    "HRGeResponseError",
    "RawHRGeJob",
    "HRGeParser",
    "HRGePipeline",
    "HRGePipelineRunResult",
]
