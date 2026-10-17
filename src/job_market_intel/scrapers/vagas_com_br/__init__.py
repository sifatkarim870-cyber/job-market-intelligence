"""Vagas.com.br (vagas.com.br) -- a Brazilian job board.

Why this source exists
----------------------
Brazil had **no** postings in the corpus. Vagas.com.br is one of the country's
larger general boards and needs no API key, no registration and no proxy.

The three traps in the payload
------------------------------
Each measured on 2026-10-18, and each one that would have broken the scraper
silently rather than loudly:

1. **``addressCountry`` is the name ``"Brasil"``, not the ISO code ``"BR"``.**
   Every other country-carrying source in this project emits an ISO code
   (``PT``, ``ZA``). ``geographic_resolution`` matches on ISO codes, so an
   unmapped ``"Brasil"`` resolves to *no country* -- and rows with no country
   collapse onto the global-remote location. The cleaner normalizes the name.

2. **``identifier`` is a ``PropertyValue`` whose ``value`` is an int.**
   Measured: ``{"@type": "PropertyValue", "name": "TP", "value": 2831966}``.
   ``str()`` is mandatory, and the URL id matches it on 3 of 3 postings.

3. **``baseSalary`` nests its numbers *flat* under ``value``** -- a sixth
   distinct layout in this codebase::

       {"currency": "BRL",
        "value": {"unitText": "MONTH", "minValue": 4300, "maxValue": 4500}}

   That is not Apna's or Mustakbil's ``value.value.minValue`` band, nor
   Wellfound's ``value.minValue``, nor Careers24's scalar. A parser written for
   any of the others reads ``None`` and stores a salary of 0 without
   complaining. It is also present on only **1 of 3** measured postings, so
   salary coverage is partial by nature of the board.

``unitText`` is ``"MONTH"``, so ``pay_period`` is **monthly** rather than the
``yearly`` default every other cleaner uses -- storing a monthly figure as
annual would overstate it twelvefold.

Also measured
------------
* **No ``employmentType`` and no ``industry``** (0 of 3). ``employment_type_code``
  is therefore honestly ``None`` rather than guessed.
* ``jobBenefits`` is a comma-separated benefits string
  ("Vale-refeição, Assistência médica, Vale-transporte"), not an array.
* ``datePosted``/``validThrough`` are plain ISO dates ("2026-08-24").
* Descriptions run 970-2834 characters, in **Portuguese**, each opening with a
  literal ``Descrição:`` label glued to the first word.
* ``addressLocality`` and ``addressRegion`` are both populated
  ("São Paulo"/"SP", "Belo Horizonte"/"MG").

Discovery
---------
``/vagas-de-emprego/`` returns **40** posting links shaped
``/vagas/v<id>/<slug>``, and the pager is real: ``?page=2`` returned **40 new
ids with zero overlap**. ``?pagina=2`` also paginates; ``?p=2`` serves a 30 KB
page with 0 postings, so it is not the parameter.

Compliance
----------
robots.txt is real ``text/plain``, 689 bytes. The ``User-Agent: *`` group
disallows ``/auth/``, ``/move_to``, ``/servicos/``, ``/v1/``, ``/api/``,
``/social/``, ``/users/``, ``/token/``, ``/vagas/pesquisas``, ``/suporte``,
``/mapa-de-carreiras/cargo/`` and ``/suporte-flix``. The listing and
``/vagas/v<id>/<slug>`` are **not** disallowed, and a ``Sitemap:`` is nominated.

Typical usage::

    from job_market_intel.scrapers.vagas_com_br import VagasComBrClient, VagasComBrParser

    records, failures = VagasComBrClient().fetch_raw_jobs()
    jobs, issues = VagasComBrParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.vagas_com_br.client import VagasComBrClient
from job_market_intel.scrapers.vagas_com_br.config import VagasComBrSettings
from job_market_intel.scrapers.vagas_com_br.exceptions import (
    VagasComBrError,
    VagasComBrFetchError,
    VagasComBrParseError,
    VagasComBrResponseError,
)
from job_market_intel.scrapers.vagas_com_br.models import RawVagasComBrJob
from job_market_intel.scrapers.vagas_com_br.parser import VagasComBrParser
from job_market_intel.scrapers.vagas_com_br.pipeline import (
    VagasComBrPipeline,
    VagasComBrPipelineRunResult,
)

__all__ = [
    "RawVagasComBrJob",
    "VagasComBrClient",
    "VagasComBrError",
    "VagasComBrFetchError",
    "VagasComBrParseError",
    "VagasComBrParser",
    "VagasComBrPipeline",
    "VagasComBrPipelineRunResult",
    "VagasComBrResponseError",
    "VagasComBrSettings",
]
