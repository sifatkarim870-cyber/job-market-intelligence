"""JobsIreland.ie (jobsireland.ie) -- Ireland's national employment service.

Why this source exists
----------------------
Ireland was the thinnest-covered country in the corpus: **261 rows, and 260 of
them from ``greenhouse``** -- Stripe, MongoDB, GitLab and Typeform postings that
happened to be located in Ireland. Not zero coverage, as an earlier note in this
project claimed; 5th lowest of 59 countries, which is the real problem. Against
a board of **3,898 postings** this is a large gain for the cheapest source built
in a while.

Correcting an earlier claim
---------------------------
A previous note here described jobsireland.ie as unwalled but with "all 188
anchors on ``/en-US/browse-jobs`` chrome, no posting links found", and parked it
as needing a different approach than anchor scraping. That was measuring the
wrong thing. The posting links exist and are plain HTML -- the site is an
**Orchard CMS** application and is server-rendered:

    <a href="/en-US/job-Details?id=2475739" role="button" class="button search-home"
       aria-label="View details of Caretaker - Soccer Field - Galbally - ...">

What made it look empty is that a **second link per card is a literal template**,
``/en-US/job-Details?id=#JobId``, with the real id substituted at runtime. An
anchor scan sees the template and no id. The id is also on the card's
``data-vacancyid`` and, most reliably, in its hidden inputs.

**No browser is needed.** That is the finding that unblocked it.

Traps, each measured 2026-10-19
-------------------------------
1. **No filter parameters may be sent.** The site's own ``searchVacancy()``
   sends six filters including ``ContractTypeId=-1``, and that set returns
   **zero cards** on a 128 KB page. ``ContractTypeId=-1`` alone takes the
   listing from 11 cards to 0 -- the handler reads ``-1`` as a real value, not a
   wildcard. ``?page=N&pageSize=M`` alone pages correctly.
2. **The listing is an HTML fragment, not JSON.**
   ``/Jobsireland.API/JobsIreland/BrowseJobs`` answers
   ``content-type: text/html`` and is the same card markup without the chrome.
   Used in preference to the full page because it honours ``pageSize`` exactly,
   where the full page returns ``pageSize + 1``.
3. **Every listing field is a hidden input**, flat in document order, one set
   per card: ``JobId``, ``JobReference``, ``CompanyLogo``, ``JobTitle``,
   ``Location``, ``StartDate``, ``EndDate``, ``VacancyTypeId``. So one request
   yields everything but the description.
4. **The listing title embeds the employer** --
   ``"Caretaker (Elton) - CE Scheme - SLIABH RI LIMITED"``. The detail page's
   ``<h3>`` is the title alone and the employer is its own ``<li>``.
5. **The detail metadata is labelled by ``img.alt``, not by class**: ``Image for
   Employer``, ``Image for Closing``, ``Image Hours per week``, and so on. The
   site's class names are almost entirely absent; these alts are stable.
6. **Addresses are four comma parts** --
   ``"<premises>, <town>, Co. <County>, <Eircode>"``, 154 of 200 sampled
   carrying an Eircode. Stored raw they resolve to nothing: ``1 of 16`` real
   addresses. Reduced to "town, county" by the cleaner: **16 of 16**.
7. **Dublin carries its postal district** -- ``Dublin 8``, ``Dublin 12`` -- and
   ``ref.cities`` holds "Dublin".
8. **There is no salary.** ``alt="Image for Euro"`` is the euro icon beside the
   *label* of a link to a programme-wide rates page, with no figure anywhere.
9. **The description node carries share-button chrome**, removed from the tree
   before the text is read rather than string-matched.
10. **An empty listing is usually transient.** The board genuinely served
    "0 job found" for several minutes partway through a 78-page walk, on every
    parameter set with no cookies set, while detail pages stayed HTTP 200. An
    empty page is retried and cross-checked against the HTML page before it is
    believed.

Compliance
----------
robots.txt: ``User-agent: *`` with no ``Disallow`` -- the whole site is
permitted.
"""

from __future__ import annotations

from job_market_intel.scrapers.jobsireland.client import JobsIrelandClient
from job_market_intel.scrapers.jobsireland.config import JobsIrelandSettings
from job_market_intel.scrapers.jobsireland.exceptions import (
    JobsIrelandError,
    JobsIrelandFetchError,
    JobsIrelandParseError,
    JobsIrelandResponseError,
)
from job_market_intel.scrapers.jobsireland.models import (
    VACANCY_TYPES,
    RawJobsIrelandJob,
)
from job_market_intel.scrapers.jobsireland.parser import (
    JobsIrelandParser,
    parse_detail,
    parse_iso_date,
    parse_listing,
    parse_long_date,
    reduce_location,
    split_listing_title,
)
from job_market_intel.scrapers.jobsireland.pipeline import (
    JobsIrelandPipeline,
    JobsIrelandPipelineRunResult,
)

__all__ = [
    "JobsIrelandCleaner",
    "JobsIrelandClient",
    "JobsIrelandError",
    "JobsIrelandFetchError",
    "JobsIrelandParseError",
    "JobsIrelandParser",
    "JobsIrelandPipeline",
    "JobsIrelandPipelineRunResult",
    "JobsIrelandResponseError",
    "JobsIrelandSettings",
    "RawJobsIrelandJob",
    "VACANCY_TYPES",
    "parse_detail",
    "parse_iso_date",
    "parse_listing",
    "parse_long_date",
    "reduce_location",
    "split_listing_title",
]
