"""Revolico (revolico.com) -- Cuba jobs.

Why this source exists
----------------------
Cuba had **zero** coverage. Revolico is the island's large general classifieds
site, and its ``Empleos`` category has an employers' sub-board,
``Ofertas de Empleo`` (the sibling ``Busco Empleo`` holds job-seekers), that is
a genuine jobs board: hundreds of employer postings paginated ~100 to a page.

No HTML scraping: the server-rendered Next.js page embeds the Apollo cache
----------------------------------------------------------------------------
There is no schema.org JSON-LD and no separate API is needed. Each search page
and each item page is server-rendered Next.js and carries its data in
``<script id="__NEXT_DATA__" type="application/json">``; the ads are the
``AdType:*`` entries of ``props.pageProps.__APOLLO_STATE__``::

    {"__typename": "AdType", "id": "55794055",
     "title": "Se busca: Custodio de La Finca",
     "description": "Se busca: Custodio de La Finca\\n_\\n...",
     "price": 1000, "currency": "CUP",
     "province": {"__ref": "ProvinceType:1"},
     "municipality": {"__ref": "MunicipalityType:43"},
     "subcategory": {"__ref": "CategoryType:1301"},
     "updatedOnByUser": "2026-11-20T20:51:46.137Z", ...}

Field contract and traps
------------------------
* Ad URLs are ``/item/<slug>-<id>`` and ``<id>`` is the stable ``source_job_id``.
* The **listing** embeds partial ``AdType`` objects (no description); the
  **detail** page embeds the full one. One request per ad is required for the
  body.
* There is **no original posting date** -- only ``updatedOnByUser`` (rendered as
  "hace 14 minutos"). Its date is used and flagged in ``raw_payload``.
* There is **no employer field**. The ad's ``name`` is the poster, not the
  business, so the employer stays "Unknown employer" rather than guessing.
* ``price``/``currency`` are unreliable (often a placeholder ``1``), so no row
  is treated as a disclosed salary; both are kept in ``raw_payload``.

Compliance
----------
robots.txt is a generic ``*`` group that allows everything except
``/checkout/``, ``/cdn-cgi/``, ``/account``, ``/auth`` and ``/favorites/``.
Pagination is the site's own ``?page={n}`` and a polite delay is kept.

Typical usage::

    from job_market_intel.scrapers.revolico_cu import (
        RevolicoCuClient,
        RevolicoCuParser,
    )

    records, failures = RevolicoCuClient().fetch_raw_jobs()
    jobs, issues = RevolicoCuParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.revolico_cu.client import RevolicoCuClient
from job_market_intel.scrapers.revolico_cu.config import RevolicoCuSettings
from job_market_intel.scrapers.revolico_cu.exceptions import (
    RevolicoCuError,
    RevolicoCuFetchError,
    RevolicoCuParseError,
    RevolicoCuResponseError,
)
from job_market_intel.scrapers.revolico_cu.models import RawRevolicoCuJob
from job_market_intel.scrapers.revolico_cu.parser import RevolicoCuParser, parse_detail
from job_market_intel.scrapers.revolico_cu.pipeline import (
    RevolicoCuPipeline,
    RevolicoCuPipelineRunResult,
)

__all__ = [
    "RawRevolicoCuJob",
    "RevolicoCuClient",
    "RevolicoCuError",
    "RevolicoCuFetchError",
    "RevolicoCuParseError",
    "RevolicoCuParser",
    "RevolicoCuPipeline",
    "RevolicoCuPipelineRunResult",
    "RevolicoCuResponseError",
    "RevolicoCuSettings",
    "parse_detail",
]
