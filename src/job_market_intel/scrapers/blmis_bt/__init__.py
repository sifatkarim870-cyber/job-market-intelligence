"""BLMIS (Bhutan Labour Market Information System) scraper.

BLMIS at ``https://www.blmis.gov.bt`` is the job portal of Bhutan's labour
ministry. The workbook's recorded domain for this state jobs portal,
``jobs.molhr``, is NXDOMAIN (see ``config.py``); BLMIS is the successor
portal, so this is a successor build in the same spirit as ``llv_li``.

The whole inventory is server-rendered into the Livewire
``wire:initial-data`` blob of the public jobseeker page
``/jobseeker_page/mispage`` -- a single, keyless, no-login GET. The client
merges the six ``job_by_*`` browse facets and de-duplicates by
``application_no`` (442 unique vacancies at scoping), and ``parser.py``
validates each into a typed ``RawBlmisJob``.

``robots.txt`` (HTTP 200) is a bare ``User-agent: *`` group with an EMPTY
``Disallow`` (allow-all). No key, no registration, no proxy, no browser;
TLS verification stays on.

Typical usage:

    from job_market_intel.scrapers.blmis_bt import (
        BlmisClient, BlmisParser, BlmisSettings,
    )

    settings = BlmisSettings()
    client = BlmisClient(settings=settings)
    parser = BlmisParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import BlmisClient
from .config import BlmisSettings
from .exceptions import (
    BlmisError,
    BlmisFetchError,
    BlmisResponseError,
)
from .models import RawBlmisJob
from .parser import BlmisParser
from .pipeline import BlmisPipeline, BlmisPipelineRunResult

__all__ = [
    "BlmisClient",
    "BlmisSettings",
    "BlmisError",
    "BlmisFetchError",
    "BlmisResponseError",
    "RawBlmisJob",
    "BlmisParser",
    "BlmisPipeline",
    "BlmisPipelineRunResult",
]
