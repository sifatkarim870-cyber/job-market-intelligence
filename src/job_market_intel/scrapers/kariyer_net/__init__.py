"""Kariyer.net scraper -- Turkiye's largest generalist job board.

Why this source exists
----------------------
Turkiye had a single source in the corpus (``iskur_gov_tr``, the state
employment agency). Kariyer.net is the private-market counterweight and one of
the largest boards in the country.

How it fetches
--------------
The ``www`` marketing HTML sits behind HUMAN/PerimeterX and hard-403s a
non-browser client, but the board's own SPA publishes two **public** JSON
gateways that are not behind that interstitial and need no key:

    POST https://candidatewebapigw.kariyer.net/jb/api/jobs/search
    GET  https://candidatesearchapigateway.kariyer.net/job?jobId=<id>

Both host names come from the site's own JavaScript bundle (``VUE_APP_API_DOMAIN``
/ ``VUE_APP_API_V4_DOMAIN``). The detail gateway answers a real Chrome TLS
handshake and rejects plain ``requests``, so this client speaks through
``curl_cffi`` -- the same fix JobsNepal and Job.am use. It must NOT send
``Api-Version``; that header turns a 200 into a 403.

Compliance
----------
robots.txt's generic ``User-agent: *`` group allows ``/is-ilanlari`` and
``/is-ilani/`` (the listing and the ad pages), which are exactly the surfaces
this scraper mirrors; it requests no disallowed path.

Typical usage::

    from job_market_intel.scrapers.kariyer_net import KariyerNetClient, KariyerNetParser

    records, failures = KariyerNetClient().fetch_raw_jobs()
    jobs = KariyerNetParser().parse_jobs(records)
"""

from __future__ import annotations

from .client import KariyerNetClient
from .config import KariyerNetSettings
from .exceptions import (
    KariyerNetError,
    KariyerNetFetchError,
    KariyerNetParseError,
    KariyerNetResponseError,
)
from .models import RawKariyerNetJob
from .parser import KariyerNetParser
from .pipeline import KariyerNetPipeline, KariyerNetPipelineRunResult

__all__ = [
    "KariyerNetClient",
    "KariyerNetError",
    "KariyerNetFetchError",
    "KariyerNetParseError",
    "KariyerNetParser",
    "KariyerNetPipeline",
    "KariyerNetPipelineRunResult",
    "KariyerNetResponseError",
    "KariyerNetSettings",
    "RawKariyerNetJob",
]
