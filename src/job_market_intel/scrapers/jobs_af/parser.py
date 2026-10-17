"""Parses a Jobs.af posting's JSON-LD into a ``RawJobsAfJob``.

The block is parsed with a plain ``json.loads`` first and ``strict=False`` only as
a fallback, because malformed blocks are common enough across this corpus that
assuming either behaviour would be luck rather than design.

Two traps, each measured 2026-10-18:

1. ``addressCountry`` is the **name** ``"Afghanistan"``, not the ISO code. The
   cleaner normalizes it; see the cleaner module docstring.

2. ``datePosted`` is ``"2026-10-17 10:48:27.175+00"`` -- milliseconds, and a
   timezone offset with **no minutes**. ``datetime.fromisoformat`` rejects that
   on 3.10 and older, so the date is taken from the leading ``YYYY-MM-DD`` by
   regex instead. That is robust to whatever the timestamp tail looks like, which
   is the point: only the calendar date is wanted here and the tail is noise.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.jobs_af.models import RawJobsAfJob

from .exceptions import JobsAfParseError

#: Leading YYYY-MM-DD. Deliberately ignores everything after it: this board
#: appends milliseconds and a truncated ``+00`` offset, neither of which is ISO
#: 8601 and neither of which the calendar date depends on.
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _parse_date(value: Any) -> date | None:
    """Take the calendar date from the front of a timestamp.

    Robust to the board's ``"2026-10-17 10:48:27.175+00"`` and to the ISO
    ``"2026-11-07T00:00:00"`` form other sources send.
    """
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
    """Pull the schema.org JobPosting out of a detail page."""
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


def _extract_location(ld: dict) -> tuple[str | None, str | None]:
    """jobLocation -> (label, country)."""
    place = ld.get("jobLocation")
    if isinstance(place, list):
        place = next((p for p in place if isinstance(p, dict)), None)
    if not isinstance(place, dict):
        return None, None
    address = place.get("address")
    if not isinstance(address, dict):
        address = {}

    def g(key: str) -> str | None:
        v = address.get(key)
        return (str(v).strip() or None) if v is not None else None

    city = g("addressLocality")
    region = g("addressRegion")
    country = g("addressCountry")
    parts: list[str] = []
    for part in (city, region):
        if part and part.casefold() not in {p.casefold() for p in parts}:
            parts.append(part)
    label = ", ".join(parts) if parts else country
    return (label or None), country


class JobsAfParser:
    """Turns a Jobs.af JSON-LD block into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawJobsAfJob:
        """Parse one posting.

        Raises:
            JobsAfParseError: No title.
        """
        ld = extract_jsonld(html or "")
        title = str(ld.get("title") or "").strip()
        if not title:
            raise JobsAfParseError(
                f"Jobs.af posting {job_id} has no title; the page carried no "
                "JobPosting title in its JSON-LD (an empty block means the "
                "markup changed or the slug no longer resolves)"
            )

        org = ld.get("hiringOrganization")
        if not isinstance(org, dict):
            org = {}
        logo = org.get("logo")
        if isinstance(logo, dict):
            logo = logo.get("url")

        location, country = _extract_location(ld)
        desc = ld.get("description")

        return RawJobsAfJob(
            source_job_id=str(job_id),
            title=title,
            company_name=str(org.get("name") or "").strip() or "Unknown employer",
            company_logo_url=logo if isinstance(logo, str) and logo.strip() else None,
            employment_type=ld.get("employmentType") or None,
            industry=ld.get("industry") or None,
            location=location,
            # The NAME, not the ISO code. The cleaner normalizes it; recording the
            # raw value here is what makes the normalization auditable.
            country=country,
            description=str(desc).strip() if desc else None,
            posted_date=_parse_date(ld.get("datePosted")),
            closing_date=_parse_date(ld.get("validThrough")),
            url=url,
            listing_page=listing_page,
            raw={
                "has_identifier": ld.get("identifier") is not None,
                "has_base_salary": isinstance(ld.get("baseSalary"), dict),
                # No corpus column exists for this; recorded rather than mapped.
                "direct_apply": ld.get("directApply"),
                "date_posted_raw": str(ld.get("datePosted") or "")[:40],
                "page_bytes": len(html or ""),
            },
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawJobsAfJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawJobsAfJob] = []
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
            except JobsAfParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Jobs.af records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
