"""OCC Mundial (occ.com.mx) scraper.

OCC is Mexico's largest job board. Its listing ships no anchor tags -- each
result is a JavaScript-clicked ``<li class="vacancy-card">`` -- so it cannot use
the generic browser framework's anchor discovery. It does publish a schema.org
``ItemList`` JSON-LD block with every ad URL, and each ad is available as clean
JSON from ``oferta.occ.com.mx``. This package reads the former with an
undetected Chrome (the listing is behind Cloudflare) and the latter with
``curl_cffi``, then hands the mapped record to the shared HTML pipeline.

See :mod:`job_market_intel.scrapers.occ_com_mx.client` for the fetch strategy.
"""

from __future__ import annotations

from job_market_intel.scrapers.occ_com_mx.client import OccComMxClient
from job_market_intel.scrapers.occ_com_mx.exceptions import (
    OccComMxChallengeError,
    OccComMxError,
    OccComMxFetchError,
)
from job_market_intel.scrapers.occ_com_mx.pipeline import (
    SOURCE_CODE,
    OccComMxPipeline,
)

__all__ = [
    "SOURCE_CODE",
    "OccComMxChallengeError",
    "OccComMxClient",
    "OccComMxError",
    "OccComMxFetchError",
    "OccComMxPipeline",
]
