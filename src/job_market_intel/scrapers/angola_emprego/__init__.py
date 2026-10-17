"""Angola Emprego (angolaemprego.com) -- an Angolan job board.

Why this source exists
----------------------
Angola had **no** postings in the corpus. Angola Emprego is an Angolan board
that needs no API key, no registration and no proxy.

The trap that would have cost the whole batch
---------------------------------------------
``employmentType`` arrives as a **list** -- ``["FULL_TIME"]`` -- not the bare
string every other source in this project emits. A cleaner written for any of
them calls ``value.strip()``, raises ``AttributeError``, and because
``clean_jobs`` catches per record, drops **every posting in the batch** while
the run still reports success. That is why
``_extract_employment_type``/``_map_employment_type`` accept both shapes, and
why it has its own tests rather than being folded into a mapping assertion.

The second trap
---------------
``identifier`` is ``{"@type": "PropertyValue", "value": "<slug string>"}`` --
a slug, neither an int nor the numeric URL suffix. Some URL slugs end ``-4818``
and others do not, so **the URL slug is the key** and the identifier is recorded
alongside it for comparison.

Also measured
-------------
* **No ``baseSalary``** on any posting, so ``salary_disclosed`` is always
  ``False`` and no ``pay_period`` is claimed about a figure that does not
  exist. This is the fourth source in the corpus where that is true (after
  Alfred, Net-Empregos and CareerJunction).
* ``datePosted``/``validThrough`` are full ISO timestamps **with a timezone
  offset**: "2026-10-17T08:30:47+00:00".
* ``addressCountry`` was not consistently present, so ``SOURCE_HOME_COUNTRY``
  supplies ``AO`` as the fallback -- which is what keeps rows from collapsing
  onto the global-remote location.
* Descriptions run 700-1300 characters, in **Portuguese**, opening with a
  literal "Sobre a Vaga" label.
* ``hiringOrganization`` carries a ``logo`` URL.
* The JSON-LD block is malformed on some pages, so the parser attempts a strict
  ``json.loads`` first and falls back to ``strict=False``.

Discovery
---------
``/vagas`` returns **15** posting links and ``?page=2`` returns **15 new** ones,
so the pager is real.

Compliance
----------
robots.txt is real ``text/plain``, 460 bytes. The ``User-agent: *`` group is
``Allow: /`` and disallows ``/login``, ``/register``, ``/perfil``, ``/planos``,
``/pagamento``, ``/vagas-sugeridas``, ``/linkstorage``, ``/auth/`` and three
query-parameter searches on the listing path -- ``/vagas?q=``,
``/vagas?location=`` and ``/vagas?category=`` -- plus ``/?s=``. Those are the
site's own duplicate-content rules. Discovery therefore walks ``?page=N`` and
never filters by query; ``?page=`` is not among the disallowed parameters, so
the pager is compliant.

Typical usage::

    from job_market_intel.scrapers.angola_emprego import (
        AngolaEmpregoClient, AngolaEmpregoParser,
    )

    records, failures = AngolaEmpregoClient().fetch_raw_jobs()
    jobs, issues = AngolaEmpregoParser().parse_many(records)
"""

from __future__ import annotations

from job_market_intel.scrapers.angola_emprego.client import AngolaEmpregoClient
from job_market_intel.scrapers.angola_emprego.config import AngolaEmpregoSettings
from job_market_intel.scrapers.angola_emprego.exceptions import (
    AngolaEmpregoError,
    AngolaEmpregoFetchError,
    AngolaEmpregoParseError,
    AngolaEmpregoResponseError,
)
from job_market_intel.scrapers.angola_emprego.models import RawAngolaEmpregoJob
from job_market_intel.scrapers.angola_emprego.parser import AngolaEmpregoParser
from job_market_intel.scrapers.angola_emprego.pipeline import (
    AngolaEmpregoPipeline,
    AngolaEmpregoPipelineRunResult,
)

__all__ = [
    "AngolaEmpregoClient",
    "AngolaEmpregoCleaner",
    "AngolaEmpregoError",
    "AngolaEmpregoFetchError",
    "AngolaEmpregoParseError",
    "AngolaEmpregoParser",
    "AngolaEmpregoPipeline",
    "AngolaEmpregoPipelineRunResult",
    "AngolaEmpregoResponseError",
    "AngolaEmpregoSettings",
    "RawAngolaEmpregoJob",
]
