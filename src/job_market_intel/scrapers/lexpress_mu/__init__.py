"""L'Express Petites Annonces (lexpress-petites-annonces.mu) -- Mauritius jobs.

Why this source exists
----------------------
Mauritius already has ``myjob`` (a JSON API board), but L'Express -- the
island's main daily newspaper -- runs a large classifieds site whose
``Emplois`` category is a genuine jobs board: mostly employer postings, with
70-194-word bodies, occasional ``MUR`` salaries, and locations. The news host
``lexpress.mu`` only links to it; the ads live on the sister host
``lexpress-petites-annonces.mu``.

No structured data
------------------
No schema.org JSON-LD. Everything is Tailwind markup extraction from a
handful of paragraphs::

    <h1 class="text-2xl font-bold w-[65%]">Pool Attendant - Azuri (Roches Noires)</h1>
    <p class="text-xs lg:text-md font-bold">Ref: 20261116-1794825510</p>
    <p class="text-sm text-gray-500">Emplois  &gt; Full-Time</p>
    <p class="mt-1 text-xs text-gray-500">16 novembre 2026</p>
    <p class="text-lg">&lt;body&gt;</p>
    <p class="text-sm text-gray-500">Localisation: Roches Noires</p>

French dates and shared classes
-------------------------------
Dates are French long form (``16 novembre 2026``) and the site-wide
``<title>`` is ``"L'Express Petites Annonces"`` -- neither the shared English
date parser nor the ``<title>`` is usable. The breadcrumb and the
``Localisation:`` line share the exact class ``text-sm text-gray-500``; the
breadcrumb is the one containing ``>``.

Compliance
----------
robots.txt on both hosts is a generic ``*`` group with an empty ``Disallow``
(allow-all). Pagination is the category's own ``?page={n}``.

Typical usage::

    from job_market_intel.scrapers.lexpress_mu import (
        LexpressMuClient,
        LexpressMuParser,
    )

    records, failures = LexpressMuClient().fetch_raw_jobs()
    jobs, issues = LexpressMuParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.lexpress_mu.client import LexpressMuClient
from job_market_intel.scrapers.lexpress_mu.config import LexpressMuSettings
from job_market_intel.scrapers.lexpress_mu.exceptions import (
    LexpressMuError,
    LexpressMuFetchError,
    LexpressMuParseError,
    LexpressMuResponseError,
)
from job_market_intel.scrapers.lexpress_mu.models import RawLexpressMuJob
from job_market_intel.scrapers.lexpress_mu.parser import LexpressMuParser, parse_detail
from job_market_intel.scrapers.lexpress_mu.pipeline import (
    LexpressMuPipeline,
    LexpressMuPipelineRunResult,
)

__all__ = [
    "LexpressMuCleaner",
    "LexpressMuClient",
    "LexpressMuError",
    "LexpressMuFetchError",
    "LexpressMuParseError",
    "LexpressMuParser",
    "LexpressMuPipeline",
    "LexpressMuPipelineRunResult",
    "LexpressMuResponseError",
    "LexpressMuSettings",
    "RawLexpressMuJob",
    "parse_detail",
]
