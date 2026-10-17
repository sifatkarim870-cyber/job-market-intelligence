"""Parses a Jobweb Ghana posting's JSON-LD into a ``RawJobwebGhanaJob``.

Two traps, each measured 2026-10-18:

1. **The listing page carries only a ``BreadcrumbList``.** The ``JobPosting``
   block is on the *detail* page. A probe of the listing -- which is what
   decides "does this board publish structured data" -- says no, and the first
   triage scored this board as "HTML extraction needed". That verdict was wrong.
   The detail page is what has to be probed before concluding a board has no
   structured data.

2. **``baseSalary`` is a site-wide placeholder.** 5 of 5 measured postings
   carry a byte-identical 1500-8000 GHS/month block, across a Chief Executive
   Officer, a CCTV Controller and an Accounts Clerk. The parser records it for
   audit and flags it; the cleaner refuses to store it. Storing it would put the
   same invented band on every Ghanaian row, in a legitimate-looking
   schema.org shape.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.jobwebghana.models import (
    _SITE_DEFAULT_SALARY,
    RawJobwebGhanaJob,
    _canonical,
)

from .exceptions import JobwebGhanaParseError

#: Leading YYYY-MM-DD of "2026-10-16T12:56:18" (no timezone on this board).
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _parse_date(value: Any) -> date | None:
    """Parse a date, tolerating a full timestamp with or without a timezone."""
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


def _load(block: str) -> Any:
    """Strict first, ``strict=False`` as a fallback."""
    try:
        return json.loads(block)
    except (TypeError, ValueError):
        pass
    try:
        return json.loads(block, strict=False)
    except (TypeError, ValueError):
        return None


def extract_jsonld(html: str) -> dict:
    """Pull the schema.org JobPosting out of a detail page.

    The listing page carries only a ``BreadcrumbList``, so this must be called
    on a **detail** page. Returns an empty dict when there is no JobPosting.
    """
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script[type='application/ld+json']"):
        block = (tag.string or tag.get_text() or "").strip()
        if not block:
            continue
        payload = _load(block)
        if payload is None:
            continue
        for node in _iter_nodes(payload):
            if node.get("@type") == "JobPosting":
                return node
    return {}


def _extract_salary(ld: dict) -> tuple[str | None, float | None, float | None, str | None, bool]:
    """``baseSalary`` -> (currency, min, max, unitText, is_site_default).

    Layout measured on this board nests the numbers under ``value`` with a
    redundant ``value`` key duplicating ``minValue``::

        {"currency": "GHS",
         "value": {"value": "1500", "minValue": "1500",
                   "maxValue": "8000", "unitText": "MONTH"}}

    The Apna/Mustakbil ``value.value`` nesting is also tolerated, since it costs
    three lines and a silent miss would store nothing.
    """
    bs = ld.get("baseSalary")
    if not isinstance(bs, dict):
        return None, None, None, None, False
    currency = bs.get("currency")
    val = bs.get("value")
    if not isinstance(val, dict):
        return (str(currency) if currency else None), None, None, None, False
    node = val if ("minValue" in val or "maxValue" in val) else val.get("value")
    if not isinstance(node, dict):
        return (str(currency) if currency else None), None, None, None, False

    def _num(v: Any) -> float | None:
        if v is None or isinstance(v, bool):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    unit = node.get("unitText")
    is_default = _canonical(bs) == _SITE_DEFAULT_SALARY
    return (
        (str(currency) if currency else None),
        _num(node.get("minValue") if node.get("minValue") is not None else node.get("value")),
        _num(node.get("maxValue")),
        (str(unit).strip() if unit and str(unit).strip() else None),
        is_default,
    )


def _extract_location(
    ld: dict,
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """jobLocation -> (label, country, city, region, postal)."""
    place = ld.get("jobLocation")
    if isinstance(place, list):
        place = next((p for p in place if isinstance(p, dict)), None)
    if not isinstance(place, dict):
        return None, None, None, None, None
    address = place.get("address")
    if not isinstance(address, dict):
        address = {}

    def g(k):
        v = address.get(k)
        return (str(v).strip() or None) if v is not None else None

    city, region, country, postal = (
        g("addressLocality"),
        g("addressRegion"),
        g("addressCountry"),
        g("postalCode"),
    )
    street = g("streetAddress")
    parts: list[str] = []
    for part in (city, region):
        if part and part.casefold() not in {p.casefold() for p in parts}:
            parts.append(part)
    label = ", ".join(parts) if parts else (country or street)
    return (label or None), country, city, region, postal


class JobwebGhanaParser:
    """Turns a Jobweb Ghana JSON-LD block into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawJobwebGhanaJob:
        """Parse one posting.

        Raises:
            JobwebGhanaParseError: No title.
        """
        ld = extract_jsonld(html or "")
        title = str(ld.get("title") or "").strip()
        if not title:
            raise JobwebGhanaParseError(
                f"Jobweb Ghana posting {job_id} has no title; the page carried no "
                "JobPosting title in its JSON-LD. Note the LISTING page carries "
                "only a BreadcrumbList, so this function must be given a detail page."
            )

        org = ld.get("hiringOrganization")
        if not isinstance(org, dict):
            org = {}
        same_as = org.get("sameAs")

        location, country, city, region, postal = _extract_location(ld)
        currency, sal_min, sal_max, unit, is_default = _extract_salary(ld)
        if is_default:
            logger.debug(
                "jobwebghana posting {} carries the site-wide placeholder salary; "
                "it is recorded for audit and rejected by the cleaner",
                job_id,
            )

        desc = ld.get("description")
        if desc:
            # Measured: descriptions carry literal \r\n sequences.
            desc = str(desc).replace("\r\n", "\n").replace("\r", "\n")

        return RawJobwebGhanaJob(
            source_job_id=str(job_id),
            title=title,
            company_name=str(org.get("name") or "").strip() or "Unknown employer",
            company_url=same_as if isinstance(same_as, str) and same_as.strip() else None,
            industry=ld.get("industry") or None,
            employment_type=ld.get("employmentType") or None,
            location=location,
            country=country,
            city=city,
            region=region,
            postal_code=postal,
            description=desc,
            salary_currency=currency,
            salary_min=sal_min,
            salary_max=sal_max,
            salary_unit_text=unit,
            salary_raw=ld.get("baseSalary") if isinstance(ld.get("baseSalary"), dict) else None,
            posted_date=_parse_date(ld.get("datePosted")),
            closing_date=_parse_date(ld.get("validThrough")),
            url=url,
            listing_page=listing_page,
            raw={
                "has_identifier": ld.get("identifier") is not None,
                "has_base_salary": isinstance(ld.get("baseSalary"), dict),
                "salary_is_site_default": is_default,
                "page_bytes": len(html or ""),
            },
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawJobwebGhanaJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawJobwebGhanaJob] = []
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
            except JobwebGhanaParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Jobweb Ghana records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
