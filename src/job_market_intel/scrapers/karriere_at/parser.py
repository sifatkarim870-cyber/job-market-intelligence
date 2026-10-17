"""Parses a Karriere.at posting's JSON-LD into a ``RawKarriereAtJob``."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.karriere_at.models import RawKarriereAtJob

from .exceptions import KarriereAtParseError


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value).strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _iter_nodes(payload):
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            yield node
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def extract_jsonld(html: str) -> dict:
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
    if value is None:
        return None
    items = value if isinstance(value, list) else [value]
    out = [str(v).strip() for v in items if str(v).strip()]
    return out or None


def _extract_identifier(ld: dict) -> str | None:
    ident = ld.get("identifier")
    if ident is None:
        return None
    if isinstance(ident, dict):
        val = ident.get("value")
        if val is not None and str(val).strip():
            return str(val).strip()
    return str(ident).strip() or None


def _extract_salary(ld: dict) -> tuple[str | None, float | None, float | None, str | None]:
    bs = ld.get("baseSalary")
    if not isinstance(bs, dict):
        return None, None, None, None
    currency = bs.get("currency")
    val = bs.get("value")
    if not isinstance(val, dict):
        return (str(currency) if currency else None), None, None, None
    node = val if ("minValue" in val or "maxValue" in val) else val.get("value")
    if not isinstance(node, dict):
        return (str(currency) if currency else None), None, None, None

    def _num(v):
        if v is None or isinstance(v, bool):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    unit = node.get("unitText")
    return (
        (str(currency) if currency else None),
        _num(node.get("minValue") if node.get("minValue") is not None else node.get("value")),
        _num(node.get("maxValue")),
        (str(unit).strip() if unit and str(unit).strip() else None),
    )


def _extract_location(ld: dict) -> tuple[str | None, str | None]:
    place = ld.get("jobLocation")
    if isinstance(place, list):
        place = next((p for p in place if isinstance(p, dict)), None)
    if not isinstance(place, dict):
        return None, None
    address = place.get("address")
    if not isinstance(address, dict):
        address = {}
    city = str(address.get("addressLocality") or "").strip() or None
    region = str(address.get("addressRegion") or "").strip() or None
    country = str(address.get("addressCountry") or "").strip() or None
    parts = []
    for part in (city, region):
        if part and part.casefold() not in {p.casefold() for p in parts}:
            parts.append(part)
    label = ", ".join(parts) if parts else country
    return (label or None), country


class KarriereAtParser:
    def parse(self, job_id, html=None, url=None, listing_page=None):
        ld = extract_jsonld(html or "")
        title = str(ld.get("title") or "").strip()
        if not title:
            raise KarriereAtParseError(f"Karriere.at posting {job_id} has no title in its JSON-LD.")
        org = ld.get("hiringOrganization")
        if not isinstance(org, dict):
            org = {}
        same_as = org.get("sameAs")
        location, country = _extract_location(ld)
        currency, sal_min, sal_max, unit = _extract_salary(ld)
        ident = _extract_identifier(ld)
        if ident and ident != job_id:
            logger.debug(
                "karriere.at posting {}: identifier.value {} differs from URL id {}",
                job_id,
                ident,
            )
        desc = ld.get("description")
        if desc:
            desc = str(desc).replace("\r\n", "\n")
        return RawKarriereAtJob(
            source_job_id=str(job_id),
            title=title,
            company_name=str(org.get("name") or "").strip() or "Unknown employer",
            company_url=same_as if isinstance(same_as, str) and same_as.strip() else None,
            location=location,
            country=country,
            description=desc,
            employment_type=_extract_employment_type(ld.get("employmentType")),
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
                "identifier_value": ident,
                "page_bytes": len(html or ""),
            },
        )

    def parse_many(self, records):
        parsed = []
        issues = []
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
            except KarriereAtParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Karriere.at records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
