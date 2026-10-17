"""Parses an Angola Emprego posting's JSON-LD into a ``RawAngolaEmpregoJob``.

The block is parsed with a plain ``json.loads`` first and
``json.loads(block, strict=False)`` only as a fallback, because the site's
blocks are malformed on some pages.

Traps handled here, each measured 2026-10-18:

* ``employmentType`` is a **list** (``["FULL_TIME"]``), not a bare string.
  Normalized to a list of strings so a ``list["FULL_TIME"]`` from a future
  change cannot crash the cleaner.
* ``identifier`` is a ``PropertyValue`` whose ``value`` is a **slug string**,
  which does not always equal the URL slug -- so the URL slug is kept as the
  key and the identifier is recorded alongside it for comparison.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.angola_emprego.models import RawAngolaEmpregoJob

from .exceptions import AngolaEmpregoParseError

#: Leading YYYY-MM-DD of a full ISO timestamp ("2026-10-17T08:30:47+00:00").
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _parse_date(value: Any) -> date | None:
    """Parse a date, tolerating a full timestamp with a timezone offset."""
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


def extract_jsonld(html: str) -> dict:
    """Pull the schema.org JobPosting out of a detail page.

    Strict ``json.loads`` first, ``strict=False`` as a fallback. Returns an
    empty dict when there is no block or neither parse succeeds.
    """
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script[type='application/ld+json']"):
        block = (tag.string or tag.get_text() or "").strip()
        if not block:
            continue
        payload = None
        for loader in (json.loads, lambda b: json.loads(b, strict=False)):
            try:
                payload = loader(block)
                break
            except (TypeError, ValueError):
                continue
        if payload is None:
            continue
        for node in _iter_nodes(payload):
            if node.get("@type") == "JobPosting":
                return node
    return {}


def _extract_employment_type(value: Any) -> list[str] | None:
    """``employmentType`` -> a list of strings.

    Measured as ``["FULL_TIME"]`` -- a **list**. Every other source here emits a
    bare string, so a cleaner written for them calls ``.strip()`` and raises
    ``AttributeError`` on every posting. Both shapes are accepted.
    """
    if value is None:
        return None
    items = value if isinstance(value, list) else [value]
    out = [str(v).strip() for v in items if str(v).strip()]
    return out or None


def _extract_identifier(ld: dict) -> str | None:
    """``identifier`` -> a string.

    Measured as ``{"@type": "PropertyValue", "name": <employer>,
    "value": "<slug string>"}`` -- a slug, not an int.
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
    return str(ident).strip() or None


def _extract_salary(ld: dict) -> tuple[str | None, float | None, float | None]:
    """``baseSalary`` -> (currency, min, max).

    No measured posting carries one. The shape is handled anyway -- flat under
    ``value`` (Vagas.com.br) or one level deeper (Apna/Mustakbil) -- because
    supporting both costs a few lines and a silent miss would store 0.
    """
    bs = ld.get("baseSalary")
    if not isinstance(bs, dict):
        return None, None, None
    currency = bs.get("currency")
    val = bs.get("value")
    if not isinstance(val, dict):
        return (str(currency) if currency else None), None, None
    node = val if ("minValue" in val or "maxValue" in val) else val.get("value")
    if not isinstance(node, dict):
        return (str(currency) if currency else None), None, None

    def _num(v: Any) -> float | None:
        if v is None or isinstance(v, bool):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return (
        (str(currency) if currency else None),
        _num(node.get("minValue")),
        _num(node.get("maxValue")),
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


class AngolaEmpregoParser:
    """Turns an Angola Emprego JSON-LD block into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawAngolaEmpregoJob:
        """Parse one posting.

        Raises:
            AngolaEmpregoParseError: No title. A posting with no title is not a
                posting.
        """
        ld = extract_jsonld(html or "")
        title = str(ld.get("title") or "").strip()
        if not title:
            raise AngolaEmpregoParseError(
                f"Angola Emprego posting {job_id} has no title; the page carried "
                "no JobPosting title in its JSON-LD (an empty block means the "
                "markup changed)"
            )

        org = ld.get("hiringOrganization")
        if not isinstance(org, dict):
            org = {}
        logo = org.get("logo")
        if isinstance(logo, dict):
            logo = logo.get("url")

        location, country, city, region = _extract_location(ld)
        currency, sal_min, sal_max = _extract_salary(ld)
        ident = _extract_identifier(ld)
        if ident and ident != job_id:
            logger.debug(
                "angola_emprego posting {}: identifier.value {!r} differs from the "
                "URL slug -- keeping the URL slug, which is always present",
                job_id,
                ident,
            )

        return RawAngolaEmpregoJob(
            source_job_id=str(job_id),
            title=title,
            company_name=str(org.get("name") or "").strip() or "Unknown employer",
            company_logo_url=logo if isinstance(logo, str) and logo.strip() else None,
            industry=ld.get("industry") or None,
            employment_type=_extract_employment_type(ld.get("employmentType")),
            location=location,
            country=country,
            city=city,
            region=region,
            description=str(ld["description"]) if ld.get("description") else None,
            salary_currency=currency,
            salary_min=sal_min,
            salary_max=sal_max,
            posted_date=_parse_date(ld.get("datePosted")),
            closing_date=_parse_date(ld.get("validThrough")),
            url=url,
            listing_page=listing_page,
            raw={
                "has_identifier": ld.get("identifier") is not None,
                "has_base_salary": isinstance(ld.get("baseSalary"), dict),
                "identifier_value": ident,
                "page_bytes": len(html or ""),
            },
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawAngolaEmpregoJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawAngolaEmpregoJob] = []
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
            except AngolaEmpregoParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Angola Emprego records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
