"""Zangia.mn (zangia.mn) scraper.

Fetches job listings from Zangia, Mongolia's long-running job board, by
walking its own keyless public JSON API and hydrating each row from the
public detail endpoint, validated into typed ``RawZangiaJob`` objects.

Discovery and data are two keyless GETs, both confirmed live during
scoping (2026-11-21):

* **Listing** - ``GET
  https://hr-api.zangia.mn/api/job/public/list/search`` answers a
  paginator envelope (``data``/``page``/``limit``/``total``/
  ``totalPages``) whose rows carry ``code``, title, company, salary and
  location (newest-first by ``sortTime``).
* **Detail** - ``GET
  https://hr-api.zangia.mn/api/job/public/detail/<code>`` returns the
  full record: HTML description/requirements/additional, skills, branch,
  job level, employment type, address and company.

The public page URL is ``https://zangia.mn/job/<code>`` (HTTP 200).

There is NO readable ``robots.txt`` anywhere on the property (``zangia.mn``,
``www.zangia.mn``, ``hr-api.zangia.mn`` and ``new-api.zangia.mn`` all
return HTTP 404 -- no policy file exists). RFC 9309 treats an absent
``robots.txt`` as "allow all", and the project owner reviewed the 404s and
approved building this source on 2026-11-21 with the 404s recorded as an
observed fact - see ``config.py`` and the source registration notes.

Typical usage:

    from job_market_intel.scrapers.zangia_mn import (
        ZangiaClient, ZangiaParser, ZangiaSettings,
    )

    settings = ZangiaSettings()
    client = ZangiaClient(settings=settings)
    parser = ZangiaParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import ZangiaClient
from .config import ZangiaSettings
from .exceptions import (
    ZangiaError,
    ZangiaFetchError,
    ZangiaResponseError,
)
from .models import RawZangiaJob
from .parser import ZangiaParser
from .pipeline import ZangiaPipeline, ZangiaPipelineRunResult

__all__ = [
    "ZangiaClient",
    "ZangiaSettings",
    "ZangiaError",
    "ZangiaFetchError",
    "ZangiaResponseError",
    "RawZangiaJob",
    "ZangiaParser",
    "ZangiaPipeline",
    "ZangiaPipelineRunResult",
]
