"""Parses a Net-Empregos posting's JSON-LD into a ``RawNetEmpregosJob``.

The ``JobPosting`` sits in a ``<script type="application/ld+json">`` block, but
the JSON is **malformed**: the ``description`` string contains raw newlines,
which makes ``json.loads`` raise ``Invalid control character``. The fix is
``json.loads(block, strict=False)``, which tolerates control characters inside
strings. Every field extracts cleanly that way -- measured over 3 postings on
2026-10-16.

The payload has no ``identifier`` and no ``baseSalary``, so the id comes from
the URL and there is no salary to map.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.net_empregos.models import RawNetEmpregosJob

from .exceptions import NetEmpregosParseError

#: Leading YYYY-MM-DD. Net-Empregos formats dates as "2026-10-16 21:47 UTC".
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
            # The block is not valid JSON even with strict=False. Try to
            # salvage it by extracting the description with a regex and
            # re-parsing.
            try:
                desc = re.search(r'"description"\s*:\s*"(.*?)"\s*[,}]', block, re.S)
                if desc:
                    fixed = block.replace(desc.group(1), desc.group(1).replace("\n", "\\n"))
                    payload = json.loads(fixed, strict=False)
                else:
                    continue
            except (TypeError, ValueError):
                continue
        for node in _iter_nodes(payload):
            if node.get("@type") == "JobPosting":
                return node
    return {}


def _extract_location(
    ld: dict,
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
    """jobLocation -> (label, country, city, region, postal, street)."""
    place = ld.get("jobLocation")
    if isinstance(place, list):
        place = next((p for p in place if isinstance(p, dict)), None)
    if not isinstance(place, dict):
        return None, None, None, None, None, None
    address = place.get("address")
    if not isinstance(address, dict):
        address = {}

    city = (address.get("addressLocality") or "").strip() or None
    region = (address.get("addressRegion") or "").strip() or None
    country = (address.get("addressCountry") or "").strip() or None
    postal = (address.get("postalCode") or "").strip() or None
    street = (address.get("streetAddress") or "").strip() or None

    parts: list[str] = []
    for part in (city, region):
        if part and part.casefold() not in {p.casefold() for p in parts}:
            parts.append(part)
    label = ", ".join(parts) if parts else country
    return (label or None), country, city, region, postal, street


class NetEmpregosParser:
    """Turns a Net-Empregos JSON-LD block into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawNetEmpregosJob:
        """Parse one posting.

        Raises:
            NetEmpregosParseError: No title. The id comes from the URL so it is
                always available, but a posting with no title is not a posting.
        """
        ld = extract_jsonld(html or "")
        title = (ld.get("title") or "").strip()
        if not title:
            raise NetEmpregosParseError(
                f"Net-Empregos posting {job_id} has no title; the page carried no "
                "JobPosting title in its JSON-LD (an empty block means the "
                "markup changed)"
            )

        org = ld.get("hiringOrganization")
        if not isinstance(org, dict):
            org = {}
        logo = org.get("logo")
        if isinstance(logo, dict):
            logo = logo.get("url")

        location, country, city, region, postal, street = _extract_location(ld)

        return RawNetEmpregosJob(
            source_job_id=str(job_id),
            title=title,
            company_name=(org.get("name") or "").strip() or "Unknown employer",
            company_logo_url=logo if isinstance(logo, str) and logo.strip() else None,
            industry=ld.get("industry") or None,
            employment_type=ld.get("employmentType") or None,
            location=location,
            country=country,
            city=city,
            region=region,
            postal_code=postal,
            street_address=street,
            description=ld.get("description") or None,
            posted_date=_parse_date(ld.get("datePosted")),
            closing_date=_parse_date(ld.get("validThrough")),
            url=url,
            listing_page=listing_page,
            raw={
                "has_identifier": "identifier" in ld,
                "has_base_salary": isinstance(ld.get("baseSalary"), dict),
                "page_bytes": len(html or ""),
            },
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawNetEmpregosJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawNetEmpregosJob] = []
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
            except NetEmpregosParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Net-Empregos records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
