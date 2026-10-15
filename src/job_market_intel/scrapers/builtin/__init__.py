"""Built In (builtin.com) -- the US tech and startup job board.

Why this source exists
----------------------
Together with Wellfound this fills the segment the corpus had none of: US
tech/startup roles, which the previously-built sources (Iran-centric, Israel,
Armenia, Mauritius, Georgia, plus remote-first aggregators) did not cover.
Built In is US-only in practice -- every posting measured carried
``applicantLocationRequirements: {"@type": "Country", "name": "USA"}``.

It is also unusually rich: 24 postings sampled on 2026-10-15 carried a
``JobPosting`` with 2-6k characters of description, posting *and* closing
dates, and a benefits list of up to 46 entries ("Offers 401(K)", "Provides
adoption assistance"). Salary is present on roughly three quarters of postings.

The one trap
------------
**The ``JobPosting`` is not at the top level of the JSON-LD.** Built In emits an
~8.8 KB document shaped ``{"@context": ..., "@graph": [ ... ]}``. A parser that
checks ``json["@type"]`` finds nothing and reports an empty board on a site
that is serving every field. ``extract_posting`` walks the whole document
instead. This was measured, not assumed -- the first probe reported "no
JobPosting on any detail page" for exactly this reason.

Shape details that also differ from the sibling schema.org sources, all measured
over 24 postings: ``hiringOrganization.logo`` is an ``ImageObject`` dict rather
than a URL string; ``jobBenefits`` is a list of strings; ``jobLocation`` is a
bare ``Place`` on 19 of 24 and a list on the other 5; coordinates sit at
``jobLocation.geo`` as a *sibling* of ``address``; and ``industry`` is a list
on 21 of 24 and a bare string on the other 3.

Compliance
----------
robots.txt is real ``text/plain``. It disallows ``/search/`` and
``/jobs*?search=``, so discovery cannot be keyword-driven and no such path is
configured. It allows ``?page=`` on a ``/jobs`` path via ``Allow: /jobs*?page=``,
which is the longer and therefore governing match under RFC 9309.

Typical usage::

    from job_market_intel.scrapers.builtin import BuiltInClient, BuiltInParser

    records, failures = BuiltInClient().fetch_raw_jobs()
    jobs, issues = BuiltInParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.builtin.client import BuiltInClient
from job_market_intel.scrapers.builtin.config import BuiltInSettings
from job_market_intel.scrapers.builtin.exceptions import (
    BuiltInError,
    BuiltInFetchError,
    BuiltInParseError,
    BuiltInResponseError,
)
from job_market_intel.scrapers.builtin.models import RawBuiltInJob
from job_market_intel.scrapers.builtin.parser import BuiltInParser
from job_market_intel.scrapers.builtin.pipeline import (
    BuiltInPipeline,
    BuiltInPipelineRunResult,
)

__all__ = [
    "BuiltInClient",
    "BuiltInError",
    "BuiltInFetchError",
    "BuiltInParseError",
    "BuiltInParser",
    "BuiltInPipeline",
    "BuiltInPipelineRunResult",
    "BuiltInResponseError",
    "BuiltInSettings",
    "RawBuiltInJob",
]
