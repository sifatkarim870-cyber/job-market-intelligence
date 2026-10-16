"""Parses a Mustakbil posting's JSON-LD into a ``RawMustakbilJob``.

The ``JobPosting`` is at the top level, so extraction is the simple case. The
parts that needed measuring rather than assuming:

``baseSalary`` nests the **band** under ``value.value`` -- the same shape Apna
uses, and different from Wellfound's and Built In's, where the band sits
directly under ``value``. Every plausible nesting is probed.

``validThrough`` arrives as ``2027-01-16T19:00:00.0000000Z`` -- seven
fractional-second digits. ``datetime.fromisoformat`` rejects that on Python
before 3.11, so the date is read from the leading ``YYYY-MM-DD`` with a regex.
This also silently discards the timezone, which is irrelevant here: the corpus
stores posting and closing dates as plain dates.

``experienceRequirements`` is a nested
``{"@type": "OccupationalExperienceRequirements", "monthsOfExperience": 12}``
object. Both that and a bare string are accepted, because only the nested form
has been observed but a board can change its mind.

``identifier.value`` is a **string** here, where Apna's is a JSON number, so it
is coerced explicitly and the original type recorded.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.mustakbil.models import RawMustakbilJob

from .exceptions import MustakbilParseError

#: schema.org ``unitText`` -> the corpus's pay_period vocabulary. Only these five
#: values may reach ``salary.job_salaries.pay_period``; anything else violates
#: ``ck_job_salaries_pay_period``, which aborts the enclosing transaction and
#: takes every later row with it.
_UNIT_TO_PERIOD = {
    "YEAR": "yearly",
    "ANNUAL": "yearly",
    "PER YEAR": "yearly",
    "MONTH": "monthly",
    "MONTHLY": "monthly",
    "WEEK": "weekly",
    "WEEKLY": "weekly",
    "DAY": "daily",
    "DAILY": "daily",
    "HOUR": "hourly",
    "HOURLY": "hourly",
}

#: Leading YYYY-MM-DD, tolerant of 7-digit fractional seconds and any offset.
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _money(value: Any) -> float | None:
    """Coerce a monetary value to a float, or ``None``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    lakh = re.fullmatch(r"(\d+(?:\.\d+)?)\s*l(?:akh)?", text, re.I)
    if lakh:
        return float(lakh.group(1)) * 100_000
    crore = re.fullmatch(r"(\d+(?:\.\d+)?)\s*cr(?:ore)?", text, re.I)
    if crore:
        return float(crore.group(1)) * 10_000_000

    text = re.sub(r"[^\d.,-]", "", text)
    if not text:
        return None
    if "," in text:
        lone = "." not in text and text.count(",") == 1 and len(text.rsplit(",", 1)[1]) != 3
        text = text.replace(",", "." if lone else "")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    """Read the leading ``YYYY-MM-DD``.

    Regex rather than ``fromisoformat`` because Mustakbil emits seven
    fractional-second digits, which older Python rejects outright.
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
    """Pull the schema.org JobPosting out of a detail page, or ``{}``."""
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


def _unit(node: dict, outer: dict) -> str | None:
    for cand in (node.get("unitText"), outer.get("unitText")):
        if isinstance(cand, str) and cand.strip():
            return cand.strip().upper()
    return None


def _extract_salary(
    ld: dict,
) -> tuple[float | None, float | None, str | None, str | None, str | None, str]:
    """baseSalary -> (min, max, period, currency, unit, shape)."""
    salary = ld.get("baseSalary")
    if not isinstance(salary, dict):
        return None, None, None, None, None, "absent"
    currency = salary.get("currency") or None
    value = salary.get("value")

    if isinstance(value, dict):
        unit = _unit(value, salary)
        low = _money(value.get("minValue"))
        high = _money(value.get("maxValue"))
        if low is None and high is None:
            # A QuantitativeValue holding a bare scalar.
            single = _money(value.get("value"))
            return single, single, _UNIT_TO_PERIOD.get(unit or ""), currency, unit, "quantitative"
        shape = "band" if "minValue" in value or "maxValue" in value else "unknown"
        return low, high, _UNIT_TO_PERIOD.get(unit or ""), currency, unit, shape

    single = _money(value)
    unit = _unit(salary, salary)
    return single, single, _UNIT_TO_PERIOD.get(unit or ""), currency, unit, "single"


def _extract_location(ld: dict) -> tuple[str | None, str | None, str | None]:
    """jobLocation -> (label, country, city)."""
    place = ld.get("jobLocation")
    if isinstance(place, list):
        place = next((p for p in place if isinstance(p, dict)), None)
    if not isinstance(place, dict):
        return None, None, None
    address = place.get("address")
    if not isinstance(address, dict):
        address = {}
    city = (address.get("addressLocality") or "").strip() or None
    region = (address.get("addressRegion") or "").strip() or None
    country = (address.get("addressCountry") or "").strip() or None

    parts: list[str] = []
    for part in (city, region):
        if part and part.casefold() not in {p.casefold() for p in parts}:
            parts.append(part)
    label = ", ".join(parts) if parts else country
    return (label or None), country, city


def _extract_experience(ld: dict) -> tuple[int | None, str | None]:
    """experienceRequirements -> (months, raw-ish string).

    The observed form is a nested
    ``{"@type": "OccupationalExperienceRequirements", "monthsOfExperience": N}``.
    A bare string is accepted too, and then only the text is kept.
    """
    node = ld.get("experienceRequirements")
    if node is None:
        return None, None
    if isinstance(node, dict):
        months = node.get("monthsOfExperience")
        try:
            months = int(months) if months is not None else None
        except (TypeError, ValueError):
            months = None
        text = ", ".join(
            f"{k}: {v}"
            for k, v in node.items()
            if not k.startswith("@") and k != "monthsOfExperience"
        )
        return months, (text or None)
    if isinstance(node, list):
        return None, json.dumps(node, ensure_ascii=False)
    return None, str(node).strip() or None


class MustakbilParser:
    """Turns a Mustakbil JSON-LD block into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_path: str | None = None,
    ) -> RawMustakbilJob:
        """Parse one posting.

        Raises:
            MustakbilParseError: No title. The id comes from the URL so it is
                always available, but a posting with no title is not a posting.
        """
        ld = extract_jsonld(html or "")
        title = (ld.get("title") or "").strip()
        if not title:
            raise MustakbilParseError(
                f"Mustakbil posting {job_id} has no title; the page carried no "
                "JobPosting title in its JSON-LD (an empty block means the "
                "markup changed)"
            )

        org = ld.get("hiringOrganization")
        if not isinstance(org, dict):
            org = {}
        identifier = ld.get("identifier")
        if not isinstance(identifier, dict):
            identifier = {}

        declared = identifier.get("value")
        if declared is not None and str(declared) != str(job_id):
            logger.warning(
                "mustakbil id mismatch: URL says {} but JSON-LD identifier says {}",
                job_id,
                declared,
            )

        logo = org.get("logo")
        if isinstance(logo, dict):
            logo = logo.get("url")

        salary_min, salary_max, salary_period, currency, unit, shape = _extract_salary(ld)
        location, country, city = _extract_location(ld)
        months, exp_raw = _extract_experience(ld)

        return RawMustakbilJob(
            source_job_id=str(job_id),
            title=title,
            company_name=(org.get("name") or "").strip() or "Unknown employer",
            company_logo_url=logo if isinstance(logo, str) and logo.strip() else None,
            employment_type=ld.get("employmentType") or None,
            months_of_experience=months,
            experience_requirements_raw=exp_raw,
            location=location,
            country=country,
            city=city,
            description=ld.get("description") or None,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_period=salary_period,
            currency_iso_code=currency,
            posted_date=_parse_date(ld.get("datePosted")),
            closing_date=_parse_date(ld.get("validThrough")),
            direct_apply=ld.get("directApply"),
            url=url or ld.get("url"),
            listing_path=listing_path,
            raw={
                "salary_shape": shape,
                "unit_text": unit,
                "identifier_value_type": type(declared).__name__,
                "page_bytes": len(html or ""),
            },
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawMustakbilJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawMustakbilJob] = []
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
            except MustakbilParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Mustakbil records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
