"""TimesJobs (timesjobs.com) scraper.

Fetches job listings from TimesJobs, an India-headquartered job board, by
walking its own keyless JSON API and hydrating each row from the public
detail endpoint, validated into typed ``RawTimesjobsJob`` objects.

Discovery and data are two keyless calls, both confirmed live during
scoping (2026-11-21):

* **Listing** - ``POST https://tjapi.timesjobs.com/search/api/v1/search/jobs/list``
  answers a paginator envelope (``total``/``page``/``size``/``totalPages``/
  ``jobs``) whose ``jobs`` rows carry title, company, location, posting
  date, skills and a truncated description (newest-first by ``postDate``).
* **Detail** -
  ``GET https://tjapi.timesjobs.com/job-api/api/jobs/public/<token>``
  (``token`` = everything after ``jobid-`` in the listing's
  ``jobDetailUrl``) returns the full record: HTML description, location
  list, salary bounds, experience range, employment type, education and
  the employer's own apply link.

The main host's ``robots.txt`` is readable and permissive
(``User-agent: *`` / ``Allow: /*``, disallowing only ``/timesJobWebApp/``,
``/logout.html``, ``/AutoLogin.html`` and ``/times_logout`` - none used).
The API host ``tjapi.timesjobs.com`` serves no readable ``robots.txt``
(``/robots.txt`` and ``/`` both return HTTP 502 from its nginx gateway);
that unreadable-policy fact is recorded rather than treated as a
permission - see ``config.py`` and the source registration notes.

Typical usage:

    from job_market_intel.scrapers.timesjobs_in import (
        TimesjobsClient, TimesjobsParser, TimesjobsSettings,
    )

    settings = TimesjobsSettings()
    client = TimesjobsClient(settings=settings)
    parser = TimesjobsParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import TimesjobsClient
from .config import TimesjobsSettings
from .exceptions import (
    TimesjobsError,
    TimesjobsFetchError,
    TimesjobsResponseError,
)
from .models import RawTimesjobsJob
from .parser import TimesjobsParser
from .pipeline import TimesjobsPipeline, TimesjobsPipelineRunResult

__all__ = [
    "TimesjobsClient",
    "TimesjobsSettings",
    "TimesjobsError",
    "TimesjobsFetchError",
    "TimesjobsResponseError",
    "RawTimesjobsJob",
    "TimesjobsParser",
    "TimesjobsPipeline",
    "TimesjobsPipelineRunResult",
]
