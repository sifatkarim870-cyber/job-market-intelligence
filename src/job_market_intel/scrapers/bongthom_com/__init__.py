"""BongThom (bongthom.com) scraper.

BongThom is one of Cambodia's largest job boards. Its public Laravel site
exposes keyless JSON routes plus a server-rendered detail page:

* **Discovery** -- ``GET
  https://bongthom.com/Job_Controller/get_all?page=N`` returns the board's
  own paginator envelope (newest-first; 278 jobs over 7 pages at scoping).
* **Structured detail** -- ``GET
  https://bongthom.com/Job_Controller/get_embed/<id>`` returns the posting's
  content as JSON (HTML description, duties, benefits, skills,
  qualifications and numeric experience years).
* **Rendered detail** -- ``GET
  https://bongthom.com/job_detail/view_detail_<id>.html`` renders the
  "Workplace Circumstances" list, the only place the displayed work
  location, salary and schedule appear.

``robots.txt`` (HTTP 200 on the site, ``www.`` and ``front.`` hosts) serves
the application's HTML page instead of a policy file, so there is no policy
to obey. No key, no registration, no login, no proxy, no browser; TLS
verification stays on.

Typical usage:

    from job_market_intel.scrapers.bongthom_com import (
        BongthomClient, BongthomParser, BongthomSettings,
    )

    settings = BongthomSettings()
    client = BongthomClient(settings=settings)
    parser = BongthomParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import BongthomClient
from .config import BongthomSettings
from .exceptions import (
    BongthomError,
    BongthomFetchError,
    BongthomResponseError,
)
from .models import RawBongthomJob
from .parser import BongthomParser
from .pipeline import BongthomPipeline, BongthomPipelineRunResult

__all__ = [
    "BongthomClient",
    "BongthomSettings",
    "BongthomError",
    "BongthomFetchError",
    "BongthomResponseError",
    "RawBongthomJob",
    "BongthomParser",
    "BongthomPipeline",
    "BongthomPipelineRunResult",
]
