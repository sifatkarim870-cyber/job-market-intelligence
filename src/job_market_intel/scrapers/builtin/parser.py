"""Parses a Built In posting's ``@graph`` JSON-LD into a ``RawBuiltInJob``.

The single most important fact about this source: the ``JobPosting`` is **not**
at the top level of the JSON-LD. Built In emits an ~8.8 KB document shaped
``{"@context": ..., "@graph": [ ... ]}``, so a parser that checks
``json["@type"]`` finds nothing at all and reports an empty board on a site
that is serving every field. :func:`extract_posting` therefore walks the whole
document rather than assuming a shape.

Field shapes that differ from the other schema.org sources here, all measured on
12 postings (2026-10-15):

  * ``hiringOrganization.logo`` is an ``ImageObject`` (``{"url": ...}``), not a
    string, so reading it directly yields a dict where a URL is expected.
  * ``jobBenefits`` is a **list of strings** ("Offers 401(K)"), where Wellfound
    puts prose in the same field.
  * ``jobLocation`` is a single ``Place`` on 10 of 12 postings and a list on
    the other 2, so both are accepted.
  * Coordinates live at ``jobLocation.geo.latitude`` -- a **sibling of**
    ``address`` on the Place node, not a child of it, unlike Wellfound's
    ``Place.latitude``. Reading ``address["geo"]`` returns nothing on every
    posting, silently, which is how this was caught.
  * ``datePosted`` is a bare date (``"2026-10-15"``) while ``validThrough`` is
    a full ISO timestamp with an offset (``"2026-11-14T05:07:48+00:00"``).
  * ``identifier`` is a ``PropertyValue``: ``name`` is the company, ``value``
    the numeric id.
  * The salary period arrives as ``unitText: "YEAR"``, which is not in the
    corpus vocabulary (hourly/daily/weekly/monthly/yearly). Passing it through
    violates ``ck_job_salaries_pay_period``, whose violation aborts the
    enclosing transaction.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.builtin.models import RawBuiltInJob

from .exceptions import BuiltInParseError

#: schema.org ``unitText`` -> the corpus's pay_period vocabulary, per
#: ck_job_salaries_pay_period. Anything unmapped returns None rather than a
#: guess, and the cleaner then falls back to a known-good value.
_UNIT_TO_PERIOD = {
    "YEAR": "yearly",
    "ANNUAL": "yearly",
    "MONTH": "monthly",
    "WEEK": "weekly",
    "DAY": "daily",
    "HOUR": "hourly",
    "MINUTE": "hourly",
}


def _money(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _parse_ts(value: Any) -> date | None:
    """Parse "2026-10-15" or "2026-11-14T05:07:48+00:00"."""
    if not value:
        return None
    text = str(value).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not m:
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})", text)
        if not m:
            return None
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _iter_nodes(payload: Any):
    """Yield every dict in a JSON-LD document, however deeply nested.

    Built In wraps its nodes in ``@graph``; other sources in this corpus put them
    at the top level. Iterating beats assuming either shape.
    """
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            yield node
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def extract_posting(html: str) -> dict:
    """Pull the schema.org JobPosting node out of a detail page.

    Returns an empty dict when the page has none. A missing block degrades the
    record rather than failing it, because the id from the URL is still valid.
    """
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            payload = json.loads(tag.string or tag.get_text() or "")
        except (TypeError, ValueError):
            continue
        for node in _iter_nodes(payload):
            if node.get("@type") == "JobPosting":
                return node
    return {}


def _extract_salary(
    ld: dict,
) -> tuple[float | None, float | None, str | None, str | None, str | None]:
    """baseSalary -> (min, max, period, currency, unit_text).

    Present on only 4 of 12 postings measured, so every branch must tolerate
    absence without raising.
    """
    salary = ld.get("baseSalary")
    if not isinstance(salary, dict):
        return None, None, None, None, None
    value = salary.get("value")
    if not isinstance(value, dict):
        return None, None, None, salary.get("currency"), None
    unit = (value.get("unitText") or "").strip().upper() or None
    return (
        _money(value.get("minValue")),
        _money(value.get("maxValue")),
        _UNIT_TO_PERIOD.get(unit or ""),
        salary.get("currency") or None,
        unit,
    )


def _format_place(place: dict) -> tuple[str | None, str | None, tuple[float, float] | None]:
    """One jobLocation entry -> (label, country, (lat, lon)).

    ``geo`` is a **sibling of** ``address`` on the Place node, not a child of
    it::

        {"@type": "Place",
         "address": {"addressLocality": "Jersey City", ...},
         "geo": {"@type": "GeoCoordinates", "latitude": 40.717495, ...}}

    Reading it as ``address["geo"]`` silently yields nothing on every posting,
    which is what happened before this was measured against a live page.
    """
    address = place.get("address") or {}
    if not isinstance(address, dict):
        address = {}
    locality = (address.get("addressLocality") or "").strip()
    region = (address.get("addressRegion") or "").strip()
    country = (address.get("addressCountry") or "").strip() or None
    parts = [p for p in (locality, region) if p]
    label = ", ".join(parts) if parts else country

    geo = place.get("geo") or {}
    lat = lon = None
    if isinstance(geo, dict):
        lat, lon = _money(geo.get("latitude")), _money(geo.get("longitude"))
    coords = (lat, lon) if lat is not None and lon is not None else None
    return (label or None), country, coords


def _extract_locations(
    ld: dict,
) -> tuple[list[str], list[str], list[tuple[float, float]]]:
    """jobLocation -> (labels, countries, coordinates), de-duplicated.

    Accepts a single ``Place`` or a list: 10 of 12 postings measured used a bare
    dict and 2 used a list, so neither can be assumed.
    """
    raw_locations = ld.get("jobLocation")
    if isinstance(raw_locations, dict):
        raw_locations = [raw_locations]
    labels: list[str] = []
    countries: list[str] = []
    coords: list[tuple[float, float]] = []
    for place in raw_locations or []:
        if not isinstance(place, dict):
            continue
        label, country, point = _format_place(place)
        if label and label not in labels:
            labels.append(label)
        if country and country not in countries:
            countries.append(country)
        if point and point not in coords:
            coords.append(point)
    return labels, countries, coords


def _applicant_countries(ld: dict) -> list[str]:
    """applicantLocationRequirements -> country names.

    A different claim from ``jobLocation``: these are the countries the employer
    will take applicants *from*, not where the job is.
    """
    raw = ld.get("applicantLocationRequirements")
    if isinstance(raw, dict):
        raw = [raw]
    out: list[str] = []
    for entry in raw or []:
        name = entry.get("name") if isinstance(entry, dict) else entry
        if name and str(name) not in out:
            out.append(str(name))
    return out


def _as_list(value: Any) -> list[str]:
    """Coerce a string-or-list field into a list of strings.

    ``industry`` is a list on 21 of 24 postings measured and a bare string on
    3, so a scalar-typed field rejects three quarters of the board. Values are
    de-duplicated with order preserved, because the same industry tag does
    appear twice on some postings.
    """
    if value is None:
        return []
    raw = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in raw:
        if item is None:
            continue
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out


def _leading_id(value: Any) -> str | None:
    """Leading digits of an ``identifier.value``, which may carry a suffix."""
    m = re.match(r"(\d{4,12})", str(value or ""))
    return m.group(1) if m else None


class BuiltInParser:
    """Turns a Built In ``@graph`` JSON-LD document into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_path: str | None = None,
    ) -> RawBuiltInJob:
        """Parse one posting.

        Raises:
            BuiltInParseError: No title. The id comes from the URL so it is
                always available, but a posting with no title is not a posting.
        """
        ld = extract_posting(html or "")
        title = (ld.get("title") or "").strip()
        if not title:
            raise BuiltInParseError(
                f"Built In posting {job_id} has no title. The page carried no "
                "JobPosting node -- either the page has no JSON-LD at all, or "
                "the node moved somewhere extract_posting does not walk."
            )

        org = ld.get("hiringOrganization") or {}
        if not isinstance(org, dict):
            org = {}

        # logo is an ImageObject here, not a bare URL string.
        logo = org.get("logo")
        if isinstance(logo, dict):
            logo = logo.get("url")
        if not logo:
            logo = ld.get("image")

        salary_min, salary_max, salary_period, currency, unit = _extract_salary(ld)
        locations, countries, coords = _extract_locations(ld)

        # identifier is a PropertyValue: name=company, value=numeric id.
        identifier = ld.get("identifier")
        if not isinstance(identifier, dict):
            identifier = {}
        declared_prefix = _leading_id(identifier.get("value"))
        if declared_prefix and declared_prefix != job_id:
            logger.warning(
                "builtin id mismatch: URL says {} but JSON-LD identifier says {}",
                job_id,
                identifier.get("value"),
            )

        benefits_raw = ld.get("jobBenefits")
        benefits = _as_list(benefits_raw)

        # "TELECOMMUTE" is the only value measured; anything else stays None
        # rather than becoming False, so "not stated" and "not remote" differ.
        location_type = ld.get("jobLocationType")
        is_remote = True if location_type == "TELECOMMUTE" else None

        return RawBuiltInJob(
            source_job_id=str(job_id),
            title=title,
            company_name=(org.get("name") or "").strip() or "Unknown employer",
            company_page_url=org.get("sameAs") or None,
            company_logo_url=logo,
            employment_type=ld.get("employmentType") or None,
            industries=_as_list(ld.get("industry")),
            direct_apply=ld.get("directApply"),
            is_remote=is_remote,
            locations=locations,
            location_countries=countries,
            coordinates=coords,
            applicant_countries=_applicant_countries(ld),
            description=ld.get("description") or None,
            benefits=benefits,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_period=salary_period,
            currency_iso_code=currency,
            posted_date=_parse_ts(ld.get("datePosted")),
            closing_date=_parse_ts(ld.get("validThrough")),
            url=url,
            listing_path=listing_path,
            raw={
                "unit_text": unit or None,
                "job_location_type": location_type,
                "identifier_name": identifier.get("name"),
                "page_bytes": len(html or ""),
            },
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawBuiltInJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawBuiltInJob] = []
        issues: list[str] = []
        for rec in records:
            try:
                parsed.append(
                    self.parse(
                        str(rec.get("job_id") or ""),
                        rec.get("html"),
                        url=rec.get("url"),
                        listing_path=rec.get("listing_path"),
                    )
                )
            except BuiltInParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Built In records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues


def _to_datetime(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime(value.year, value.month, value.day)
