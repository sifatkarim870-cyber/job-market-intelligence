"""Parses a CareerJunction posting's JSON-LD into a ``RawCareerJunctionJob``.

The ``JobPosting`` sits in a ``<script type="application/ld+json">`` block, but
the JSON is **malformed**: the ``description`` string contains raw newlines and
HTML entities, which makes ``json.loads`` raise ``Invalid control character``.
The fix is ``json.loads(block, strict=False)``, which tolerates control
characters inside strings. Every field extracts cleanly that way.

The payload has no ``identifier`` and no real ``baseSalary`` (the value is
``"R Undisclosed"``), so the id comes from the URL and there is no salary to
map.

``datePosted`` / ``validThrough`` are formatted ``"2026/10/16 10:33:33 AM"``
-- not ISO 8601. A custom date parser handles this.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.careerjunction.models import RawCareerJunctionJob

from .exceptions import CareerJunctionParseError

#: CareerJunction formats dates as "2026/10/16 10:33:33 AM".
_DATE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


def _parse_date(value: Any) -> date | None:
    """Parse a date, tolerating CareerJunction's custom format."""
    if not value:
        return None
    m = _DATE.search(str(value).strip())
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

    Uses ``json.loads(block, strict=False)`` because the site's JSON-LD is
    malformed -- the description string contains raw newlines. Returns an
    empty dict when there is no block or it cannot be parsed.
    """
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script[type='application/ld+json']"):
        block = (tag.string or tag.get_text() or "").strip()
        if not block:
            continue
        try:
            payload = json.loads(block, strict=False)
        except (TypeError, ValueError):
            continue
        for node in _iter_nodes(payload):
            if node.get("@type") == "JobPosting":
                return node
    return {}


def _extract_location(
    ld: dict,
) -> tuple[str | None, str | None, str | None, float | None, float | None]:
    """jobLocation -> (label, country, city, lat, lon)."""
    place = ld.get("jobLocation")
    if isinstance(place, list):
        place = next((p for p in place if isinstance(p, dict)), None)
    if not isinstance(place, dict):
        return None, None, None, None, None
    address = place.get("address")
    if not isinstance(address, dict):
        address = {}
    city = (address.get("addressLocality") or "").strip() or None
    country = (address.get("addressCountry") or "").strip() or None

    lat = lon = None
    geo = place.get("geo")
    if isinstance(geo, dict):
        try:
            lat = float(geo.get("latitude"))
            lon = float(geo.get("longitude"))
        except (TypeError, ValueError):
            pass

    label = city or country
    return (label or None), country, city, lat, lon


class CareerJunctionParser:
    """Turns a CareerJunction JSON-LD block into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawCareerJunctionJob:
        """Parse one posting.

        Raises:
            CareerJunctionParseError: No title. The id comes from the URL so it
                is always available, but a posting with no title is not a
                posting.
        """
        ld = extract_jsonld(html or "")
        title = (ld.get("title") or "").strip()
        if not title:
            raise CareerJunctionParseError(
                f"CareerJunction posting {job_id} has no title; the page carried "
                "no JobPosting title in its JSON-LD (an empty block means the "
                "markup changed)"
            )

        org = ld.get("hiringOrganization")
        if not isinstance(org, dict):
            org = {}
        org_url = org.get("url")
        if isinstance(org_url, dict):
            org_url = org_url.get("url")

        location, country, city, lat, lon = _extract_location(ld)

        salary = ld.get("baseSalary")
        if salary is not None:
            # Not seen on the measured posting, but if it ever appears,
            # ignoring it silently would be worse than saying so.
            logger.warning(
                "CareerJunction posting {!r} now carries baseSalary; this "
                "scraper has no salary handling. Re-measure before trusting "
                "the coverage numbers.",
                job_id,
            )

        return RawCareerJunctionJob(
            source_job_id=str(job_id),
            title=title,
            company_name=(org.get("name") or "").strip() or "Unknown employer",
            company_url=org_url if isinstance(org_url, str) and org_url.strip() else None,
            industry=ld.get("industry") or None,
            employment_type=ld.get("employmentType") or None,
            location=location,
            country=country,
            city=city,
            latitude=lat,
            longitude=lon,
            description=ld.get("description") or None,
            posted_date=_parse_date(ld.get("datePosted")),
            closing_date=_parse_date(ld.get("validThrough")),
            url=url,
            listing_page=listing_page,
            raw={
                "has_identifier": "identifier" in ld,
                "has_base_salary": isinstance(salary, dict),
                "page_bytes": len(html or ""),
            },
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawCareerJunctionJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawCareerJunctionJob] = []
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
            except CareerJunctionParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} CareerJunction records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
