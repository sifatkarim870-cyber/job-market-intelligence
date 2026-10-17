"""Corporate Staffing Services (corporatestaffing.co.ke) -- a Kenyan job board.

Why this source exists
----------------------
Kenya had brightmonday.co.ke (workbook-verdict "HTML scraper") but that board is
Cloudflare-walled from datacenter IPs, so it never produced a single row. Corporate
Staffing is the working substitute: no key, no registration, no proxy, and it
paginates -- /jobs/ carries 40 postings and /jobs/page/2/ adds 40 new ones.

No structured data
-------------------
No schema.org JSON-LD. Everything is in labelled rows::

    Date Posted: 16/10/2026
    Job Type: Full Time
    Employer: APA Life Assurance Company Ltd
    Salary: Open
    Location: Nairobi
    Deadline: 26/10/2026

with the body in main. og:title IS the job title here (contrast Fiji Sun, where
it is the site's name) but <h1> is the same string and is closer to the data, so
the h1 is preferred.

Salary is prose, not a figure
------------------------------
Salary reads "Open" / "Confidential" -- the same class of non-number as
CareerJunction's "R Undisclosed" and ACBAR's "Negotiable" -- so no salary is
stored. The verbatim string is kept in raw_payload["salary_text"].

Dates are dd/mm/yyyy
--------------------
Kenyan convention: 16/10/2026 is 16 October, not 10 April. A parser that assumes
ISO returns nothing for every posting.

Compliance
----------
robots.txt: User-agent: * with an empty Disallow:. The whole site is permitted.

Typical usage::

    from job_market_intel.scrapers.corporatestaffing_ke import (
        CorporateStaffingClient, CorporateStaffingParser,
    )

    records, failures = CorporateStaffingClient().fetch_raw_jobs()
    jobs, issues = CorporateStaffingParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.corporatestaffing_ke.client import CorporateStaffingClient
from job_market_intel.scrapers.corporatestaffing_ke.config import CorporateStaffingSettings
from job_market_intel.scrapers.corporatestaffing_ke.exceptions import (
    CorporateStaffingError,
    CorporateStaffingFetchError,
    CorporateStaffingParseError,
    CorporateStaffingResponseError,
)
from job_market_intel.scrapers.corporatestaffing_ke.models import RawCorporateStaffingJob
from job_market_intel.scrapers.corporatestaffing_ke.parser import (
    CorporateStaffingParser,
    parse_detail,
)
from job_market_intel.scrapers.corporatestaffing_ke.pipeline import (
    CorporateStaffingPipeline,
    CorporateStaffingPipelineRunResult,
)

__all__ = [
    "CorporateStaffingCleaner",
    "CorporateStaffingClient",
    "CorporateStaffingError",
    "CorporateStaffingFetchError",
    "CorporateStaffingParseError",
    "CorporateStaffingParser",
    "CorporateStaffingPipeline",
    "CorporateStaffingPipelineRunResult",
    "CorporateStaffingResponseError",
    "CorporateStaffingSettings",
    "RawCorporateStaffingJob",
    "parse_detail",
]
