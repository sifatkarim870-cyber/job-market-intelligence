"""JobMail (jobmail.co.za) -- South Africa's largest job board.

Why this source exists
----------------------
South Africa had **178** rows in the corpus, from two other boards. JobMail
holds **at least 8,000** postings -- the listing paginates to 400+ pages with
20 fresh postings on each and no end in sight -- so this is the largest single
win available for the country.

It is unwalled, needs no key, and needs **no browser**: the site is
server-rendered and serves both the listing and the detail page in a plain
GET.

Traps, each measured 2026-10-19
-------------------------------
1. **"Market Related" is a salary that is not a figure.** The listing card's
   ``div.job-info`` holds either a rand range -- ``R20 000,00 - R30 000,00`` --
   or the words "Market Related", which is the board saying a salary exists
   but is not published. Parsing it for digits would invent one, so it is kept
   as a distinct ``salary_undisclosed`` flag.
2. **Rand amounts use a space for thousands and a comma for decimals** --
   ``R20 000,00`` -- and the separator is sometimes a **non-breaking space**.
3. **The location's granularity varies.** ``addressLocality`` is a city on
   some postings ("Pretoria") and a **province** on others ("Western Cape",
   "KwaZulu-Natal"), with ``addressRegion`` the same value. A single "town"
   field would be wrong half the time, so both are kept and joined as
   "town, province" for the resolver.
4. **The card's date may carry a non-breaking space** -- "04 September 2026"
   -- and a plain ``split()`` on it produces a broken month.
5. **The id is in two places**: the card's ``id="results-item-7568798"`` and
   the link's ``-id-7568798`` slug. Either is enough; the other confirms it.

The detail page's schema.org ``JobPosting`` carries the body (1,432-5,510
characters measured), the employer's own posted and closing dates, the
employment type, the employer's name and URL, and on some postings a numeric
``baseSalary`` in ZAR per month.

Compliance
----------
robots.txt: ``User-agent: *`` with only ``/setup-alerts/*`` disallowed.
"""

from __future__ import annotations

from job_market_intel.scrapers.jobmail.client import JobMailClient
from job_market_intel.scrapers.jobmail.config import JobMailSettings
from job_market_intel.scrapers.jobmail.exceptions import (
    JobMailError,
    JobMailFetchError,
    JobMailParseError,
    JobMailResponseError,
)
from job_market_intel.scrapers.jobmail.models import (
    EMPLOYMENT_TYPES,
    UNIT_TO_PAY_PERIOD,
    RawJobMailJob,
)
from job_market_intel.scrapers.jobmail.parser import (
    JobMailParser,
    parse_cadence,
    parse_card_date,
    parse_card_salary,
    parse_detail,
    parse_listing,
    parse_rand_amount,
)
from job_market_intel.scrapers.jobmail.pipeline import (
    JobMailPipeline,
    JobMailPipelineRunResult,
)

__all__ = [
    "EMPLOYMENT_TYPES",
    "JobMailCleaner",
    "JobMailClient",
    "JobMailError",
    "JobMailFetchError",
    "JobMailParseError",
    "JobMailParser",
    "JobMailPipeline",
    "JobMailPipelineRunResult",
    "JobMailResponseError",
    "JobMailSettings",
    "RawJobMailJob",
    "UNIT_TO_PAY_PERIOD",
    "parse_card_date",
    "parse_card_salary",
    "parse_cadence",
    "parse_detail",
    "parse_listing",
    "parse_rand_amount",
]
