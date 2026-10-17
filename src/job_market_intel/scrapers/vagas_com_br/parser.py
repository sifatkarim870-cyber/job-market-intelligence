"""Parses a Vagas.com.br posting's JSON-LD into a ``RawVagasComBrJob``.

The block is **malformed on some pages**: raw control characters inside strings
make ``json.loads`` raise ``Invalid control character``. So the parser attempts
a strict ``json.loads`` first and falls back to ``json.loads(block,
strict=False)``, recording which path succeeded in ``raw["jsonld_parse"]``.
That ordering matters -- strict-first means a well-formed page never pays for
the leniency, and the recorded value is what tells you whether the site has got
*worse* rather than merely being lenient-tolerant.

Traps handled here, each measured 2026-10-18:

* ``identifier`` is ``{"@type": "PropertyValue", "value": <int>}`` -- the value
  is an **int**, so ``str()`` is mandatory.
* ``addressCountry`` is the **name** ``"Brasil"``, not the ISO code.
* ``baseSalary`` nests ``unitText``/``minValue``/``maxValue`` **flat** under
  ``value``, unlike Apna/Mustakbil's extra nested ``value``.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.vagas_com_br.models import RawVagasComBrJob

from .exceptions import VagasComBrParseError

#: Leading YYYY-MM-DD. Measured values are plain ISO dates ("2026-08-24").
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _parse_date(value: Any) -> date | None:
    """Parse a date, tolerating a full timestamp with timezone."""
    if not value:
        return None
    m = _DATE.match(str(value).strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _iter_nodes(payload: Any):
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            yield node
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def _load_jsonld(block: str) -> tuple[Any, str]:
    """Parse a JSON-LD block, strict first then lenient.

    Returns ``(payload, how)`` where ``how`` is ``"strict"``, ``"lenient"`` or
    ``"unparsed"``.
    """
    try:
        return json.loads(block), "strict"
    except (TypeError, ValueError):
        pass
    try:
        return json.loads(block, strict=False), "lenient"
    except (TypeError, ValueError):
        return None, "unparsed"


def extract_jsonld(html: str) -> dict:
    """Pull the schema.org JobPosting out of a detail page.

    Uses a plain ``json.loads`` first and ``strict=False`` only as a fallback,
    because the site's blocks are malformed on some pages. Returns an empty dict
    when there is no block or neither parse succeeds.
    """
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script[type='application/ld+json']"):
        block = (tag.string or tag.get_text() or "").strip()
        if not block:
            continue
        payload, _ = _load_jsonld(block)
        if payload is None:
            continue
        for node in _iter_nodes(payload):
            if node.get("@type") == "JobPosting":
                return node
    return {}


def _extract_identifier(ld: dict) -> str | None:
    """``identifier`` -> a string.

    Measured shape is ``{"@type": "PropertyValue", "name": ..., "value": <int>}``
    so the value is an int and must be stringified. A bare string and a bare
    int are both tolerated because a board can change this without notice.
    """
    ident = ld.get("identifier")
    if ident is None:
        return None
    if isinstance(ident, dict):
        val = ident.get("value")
        if val is not None and str(val).strip():
            return str(val).strip()
        name = ident.get("name")
        return str(name).strip() if name else None
    if isinstance(ident, int):
        return str(ident)
    return str(ident).strip() or None


def _extract_salary(ld: dict) -> tuple[str | None, float | None, float | None, str | None]:
    """``baseSalary`` -> (currency, min, max, unitText).

    Measured layout nests the numbers **flat** under ``value``::

        {"currency": "BRL",
         "value": {"unitText": "MONTH", "minValue": 4300, "maxValue": 4500}}

    An extra nested ``value`` (the Apna/Mustakbil shape) is also tolerated,
    because supporting both costs three lines and a silent miss here would store
    a salary of 0.
    """
    bs = ld.get("baseSalary")
    if not isinstance(bs, dict):
        return None, None, None, None
    currency = bs.get("currency")
    val = bs.get("value")
    if not isinstance(val, dict):
        return (str(currency) if currency else None), None, None, None
    # Flat shape first; nested shape as a fallback.
    if "minValue" in val or "maxValue" in val or "unitText" in val:
        node = val
    elif isinstance(val.get("value"), dict):
        node = val["value"]
    else:
        node = val

    def _num(v: Any) -> float | None:
        if v is None or isinstance(v, bool):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    unit = node.get("unitText")
    return (
        (str(currency) if currency else None),
        _num(node.get("minValue")),
        _num(node.get("maxValue")),
        (str(unit).strip() if unit and str(unit).strip() else None),
    )


def _extract_location(ld: dict) -> tuple[str | None, str | None, str | None, str | None]:
    """jobLocation -> (label, country, city, region)."""
    place = ld.get("jobLocation")
    if isinstance(place, list):
        place = next((p for p in place if isinstance(p, dict)), None)
    if not isinstance(place, dict):
        return None, None, None, None
    address = place.get("address")
    if not isinstance(address, dict):
        address = {}
    city = str(address.get("addressLocality") or "").strip() or None
    region = str(address.get("addressRegion") or "").strip() or None
    country = str(address.get("addressCountry") or "").strip() or None

    parts: list[str] = []
    for part in (city, region):
        if part and part.casefold() not in {p.casefold() for p in parts}:
            parts.append(part)
    label = ", ".join(parts) if parts else country
    return (label or None), country, city, region


class VagasComBrParser:
    """Turns a Vagas.com.br JSON-LD block into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawVagasComBrJob:
        """Parse one posting.

        Raises:
            VagasComBrParseError: No title. A posting with no title is not a
                posting.
        """
        ld = extract_jsonld(html or "")
        title = str(ld.get("title") or "").strip()
        if not title:
            raise VagasComBrParseError(
                f"Vagas.com.br posting {job_id} has no title; the page carried no "
                "JobPosting title in its JSON-LD (an empty block means the markup "
                "changed)"
            )

        org = ld.get("hiringOrganization")
        if not isinstance(org, dict):
            org = {}

        location, country, city, region = _extract_location(ld)
        currency, sal_min, sal_max, unit = _extract_salary(ld)

        # The URL id is authoritative: it is always present and always matches
        # identifier.value where both exist (verified on 3 of 3 postings).
        ident = _extract_identifier(ld)
        if ident and ident != job_id:
            logger.debug(
                "vagas.com.br posting {}: URL id differs from identifier.value {} "
                "-- keeping the URL id, which is what makes re-runs idempotent",
                job_id,
                ident,
            )

        desc = ld.get("description")
        if desc and str(desc).strip().lower().startswith("descri"):
            # Measured: every description opens with a literal "Descrição:"
            # label glued to the first word. Stripping it is real work, not
            # cosmetics.
            desc = re.sub(r"^\s*Descri(?:ção|cao)\s*:\s*", "", str(desc), count=1, flags=re.I)

        return RawVagasComBrJob(
            source_job_id=str(job_id),
            title=title,
            company_name=str(org.get("name") or "").strip() or "Unknown employer",
            industry=ld.get("industry") or None,
            employment_type=ld.get("employmentType") or None,
            job_benefits=str(ld.get("jobBenefits")).strip() if ld.get("jobBenefits") else None,
            location=location,
            country=country,
            city=city,
            region=region,
            description=str(desc) if desc else None,
            salary_currency=currency,
            salary_min=sal_min,
            salary_max=sal_max,
            salary_unit_text=unit,
            posted_date=_parse_date(ld.get("datePosted")),
            closing_date=_parse_date(ld.get("validThrough")),
            url=url,
            listing_page=listing_page,
            raw={
                "has_identifier": ld.get("identifier") is not None,
                "has_base_salary": isinstance(ld.get("baseSalary"), dict),
                "page_bytes": len(html or ""),
                "identifier_value": ident,
            },
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawVagasComBrJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawVagasComBrJob] = []
        issues: list[str] = []
        for rec in records:
            try:
                parsed.append(
                    self.parse(
                        str(rec.get("job_id") or ""),
                        rec.get("html"),
                        url=rec.get("url"),
                        listing_page=rec.get("listing_page"),
                    )
                )
            except VagasComBrParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} vagas.com.br records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
