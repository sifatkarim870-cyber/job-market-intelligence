"""Bdjobs (bdjobs.com) scraper.

Fetches job listings from Bdjobs, Bangladesh's largest job board, by
walking its own keyless JSON API and hydrating each row from the public
detail endpoint, validated into typed ``RawBdjobsJob`` objects.

Discovery and data are two keyless calls, both confirmed live during
scoping (2026-11-21) and copied from the site's own bundled config chunk:

* **Search** - ``GET
  https://api.bdjobs.com/jobs/api/v1/JobSearch/GetJobSearch`` with
  ``pg=N&rpp=100`` answers ``{message, statuscode, data[], premiumData[],
  common{total_records_found, totalpages, total_vacancies}}`` (newest-first;
  ~5,747 rows over 58 pages at scoping). ``data`` and ``premiumData`` are
  merged and de-duplicated by ``Jobid``.
* **Detail** - ``GET
  https://api.bdjobs.com/jobs/api/v1/JobSubsystem/jobDetails`` with
  ``jobId=<id>&ln=1&IsCorporate=false`` returns the full record: HTML
  description, ``JobNature``, ``JobWorkPlace``, salary bounds, education,
  skills, experience and the public logo URL.

The HTML hosts ``bdjobs.com`` and ``jobs.bdjobs.com`` each carry a
``User-agent: *`` group ending in ``Disallow: /``, so neither is fetched.
The API host ``api.bdjobs.com`` answers HTTP 404 for ``/robots.txt`` (no
policy file), which RFC 9309 treats as "unavailable" and permits access --
the same allow-on-404 reading this repo applied to
``jobs.smartrecruiters.com`` for ``llv_li``. No key, no registration, no
proxy, no browser; TLS verification stays on.

Typical usage:

    from job_market_intel.scrapers.bdjobs_com import (
        BdjobsClient, BdjobsParser, BdjobsSettings,
    )

    settings = BdjobsSettings()
    client = BdjobsClient(settings=settings)
    parser = BdjobsParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import BdjobsClient
from .config import BdjobsSettings
from .exceptions import (
    BdjobsError,
    BdjobsFetchError,
    BdjobsResponseError,
)
from .models import RawBdjobsJob
from .parser import BdjobsParser
from .pipeline import BdjobsPipeline, BdjobsPipelineRunResult

__all__ = [
    "BdjobsClient",
    "BdjobsSettings",
    "BdjobsError",
    "BdjobsFetchError",
    "BdjobsResponseError",
    "RawBdjobsJob",
    "BdjobsParser",
    "BdjobsPipeline",
    "BdjobsPipelineRunResult",
]
