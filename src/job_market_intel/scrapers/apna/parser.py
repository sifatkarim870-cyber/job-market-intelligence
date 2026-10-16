"""Parses an Apna posting's JSON-LD into a ``RawApnaJob``.

The ``JobPosting`` sits at the top level of the document, so extraction is the
simple case. What matters here are the three shapes that differ from every
sibling source in this project:

``identifier.value`` is a JSON **number**. Written as ``job["identifier"]["value"]``
into a ``str``-typed field it survives, but any code that treats it as text --
logging it into a URL, comparing it lexicographically against a string -- breaks
silently. It is coerced to ``str`` immediately and the type is recorded.

``baseSalary`` nests the **band** under ``value.value``::

    {"currency": "INR",
     "value": {"@type": "QuantitativeValue",
               "minValue": 180000, "maxValue": 280000, "unitText": "MONTH"}}

This is the fourth distinct salary layout here: Wellfound and Built In put
``minValue``/``maxValue`` directly under ``value``, and Careers24 puts a bare
scalar under ``value.value``. A parser written for any of the other three reads
``None`` for both bounds here. Every bound is probed in every plausible
position rather than one being assumed.

``addressCountry`` is the ISO code ``"IN"``. The resolver and
``SOURCE_HOME_COUNTRY`` both work in country names or codes depending on the
path, so this is passed through unchanged rather than being translated into a
country the source never stated.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.apna.models import RawApnaJob

from .exceptions import ApnaParseError

#: schema.org ``unitText`` -> the corpus's pay_period vocabulary. The corpus
#: allows only these five values; anything else violates
#: ``ck_job_salaries_pay_period``, whose violation aborts the enclosing
#: transaction and takes every later row with it.
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


#: Indian magnitude suffixes. "1.8 L" and "2.5 Cr" are ordinary in job ads here
#: and are wrong by five or seven orders of magnitude if the suffix is dropped.
_INDIAN_MAGNITUDES = (("l", "lakh", 100_000), ("cr", "crore", 10_000_000))


def _indian_magnitude(text: str) -> float | None:
    """Parse ``"1.8 L"`` / ``"2.5 Cr"`` style amounts, or return None."""
    for short, long, scale in _INDIAN_MAGNITUDES:
        match = re.fullmatch(rf"(\d+(?:\.\d+)?)\s*{short}(?:{long})?", text, re.I)
        if match:
            return float(match.group(1)) * scale
    return None


def _money(value: Any) -> float | None:
    """Coerce a schema.org monetary value to a float, or ``None``.

    Apna emits numbers, but ``baseSalary`` is often hand-entered by employers
    and arrives formatted ("1.8 L", "₹1,80,000"). Anything that is not
    recognisably numeric returns ``None`` rather than a wrong figure -- a
    plausible-looking wrong number in a research corpus is worse than a gap.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    magnitude = _indian_magnitude(text)
    if magnitude is not None:
        return magnitude

    # Strip currency symbols, ISO codes and other decoration.
    text = re.sub(r"[^\d.,-]", "", text)
    if not text:
        return None

    # The separator is ambiguous ("650,000" vs "650,00"), so the standard
    # heuristic: a lone comma with no dot and a non-3-digit tail is a decimal
    # point. Repeated dots can only be thousands separators.
    if "," in text:
        lone_comma_decimal = (
            "." not in text and text.count(",") == 1 and len(text.rsplit(",", 1)[1]) != 3
        )
        text = text.replace(",", "." if lone_comma_decimal else "")
    elif text.count(".") > 1:
        text = text.replace(".", "")

    try:
        return float(text)
    except ValueError:
        return None


def _parse_ts(value: Any) -> date | None:
    """Parse a date, tolerating a full ISO timestamp."""
    if not value:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value).strip())
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _iter_nodes(payload: Any):
    """Yield every dict in a JSON-LD document, however deeply nested."""
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

    Returns an empty dict when there is none. A missing block degrades the
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


def _first(mapping: dict, *keys: str) -> Any:
    """First non-empty value among ``keys``.

    Used for the salary bounds: probing every plausible nesting position is
    cheaper than being wrong about which one this board chose, and a board can
    change its mind without warning.
    """
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", {}):
            return value
    return None


def _extract_salary(
    ld: dict,
) -> tuple[float | None, float | None, str | None, str | None, str | None, str]:
    """baseSalary -> (min, max, period, currency, unit, shape).

    ``shape`` is kept in the raw payload so a markup change shows up as a
    coverage number rather than as a quiet drop to zero salary rows.
    """
    salary = ld.get("baseSalary")
    if not isinstance(salary, dict):
        return None, None, None, None, None, "absent"
    currency = salary.get("currency") or None
    value = salary.get("value")
    if not isinstance(value, dict):
        # A bare scalar. Not what Apna does today, but it is the shape
        # Careers24 emits, so it is read rather than assumed impossible.
        single = _money(value)
        unit = salary.get("unitText")
        unit = unit.strip().upper() if isinstance(unit, str) and unit.strip() else None
        return single, single, _UNIT_TO_PERIOD.get(unit or ""), currency, unit, "scalar"

    unit = _first(value, "unitText") or salary.get("unitText")
    unit = unit.strip().upper() if isinstance(unit, str) and unit.strip() else None

    low = _money(_first(value, "minValue", "value", "lowValue"))
    high = _money(_first(value, "maxValue", "value", "highValue"))
    if low is None and high is None:
        return None, None, None, currency, unit, "empty"
    shape = "band" if (low != high or "minValue" in value) else "quantitative"
    return low, high, _UNIT_TO_PERIOD.get(unit or ""), currency, unit, shape


def _extract_location(
    ld: dict,
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
    """jobLocation -> (label, country, city, region, postal_code, street)."""
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

    # A posting with no locality puts the state in addressLocality, which would
    # otherwise emit "Karnataka, Karnataka".
    parts: list[str] = []
    for part in (city, region):
        if part and part.casefold() not in {p.casefold() for p in parts}:
            parts.append(part)
    label = ", ".join(parts) if parts else country
    return (label or None), country, city, region, postal, street


def _extract_skills(ld: dict) -> list[str]:
    """``skills`` is a list of short strings; measured 0-11 entries, on 15/30."""
    skills = ld.get("skills")
    if isinstance(skills, str):
        skills = [skills]
    if not isinstance(skills, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in skills:
        if not isinstance(item, str):
            continue
        cleaned = re.sub(r"\s+", " ", item).strip()
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            out.append(cleaned)
    return out


class ApnaParser:
    """Turns an Apna JSON-LD block into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawApnaJob:
        """Parse one posting.

        Raises:
            ApnaParseError: No title. The id comes from the URL so it is always
                available, but a posting with no title is not a posting.
        """
        ld = extract_jsonld(html or "")
        title = (ld.get("title") or "").strip()
        if not title:
            raise ApnaParseError(
                f"Apna posting {job_id} has no title; the page carried no "
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
                "apna id mismatch: URL says {} but JSON-LD identifier says {}", job_id, declared
            )

        logo = org.get("logo")
        if isinstance(logo, dict):
            # Built In emits an ImageObject here; Apna a plain URL string.
            logo = logo.get("url")

        applicants = ld.get("applicantLocationRequirements")
        if isinstance(applicants, list):
            applicants = next((a for a in applicants if isinstance(a, dict)), None)
        applicant_country = (applicants or {}).get("name") if isinstance(applicants, dict) else None

        salary_min, salary_max, salary_period, currency, unit, shape = _extract_salary(ld)
        location, country, city, region, postal, street = _extract_location(ld)

        return RawApnaJob(
            source_job_id=str(job_id),
            title=title,
            company_name=(org.get("name") or "").strip() or "Unknown employer",
            company_logo_url=logo if isinstance(logo, str) and logo.strip() else None,
            industry=ld.get("industry") or None,
            occupational_category=ld.get("occupationalCategory") or None,
            employment_type=ld.get("employmentType") or None,
            skills=_extract_skills(ld),
            experience_requirements=(
                json.dumps(ld["experienceRequirements"], ensure_ascii=False)
                if isinstance(ld.get("experienceRequirements"), (dict, list))
                else (str(ld["experienceRequirements"]).strip() or None)
                if ld.get("experienceRequirements")
                else None
            ),
            location=location,
            country=country,
            city=city,
            region=region,
            postal_code=postal,
            street_address=street,
            description=ld.get("description") or None,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_period=salary_period,
            currency_iso_code=currency,
            posted_date=_parse_ts(ld.get("datePosted")),
            closing_date=_parse_ts(ld.get("validThrough")),
            direct_apply=ld.get("directApply"),
            applicant_country=applicant_country,
            url=url or ld.get("url"),
            listing_page=listing_page,
            raw={
                "salary_shape": shape,
                "unit_text": unit,
                "identifier_value_type": type(declared).__name__,
                "page_bytes": len(html or ""),
            },
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawApnaJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawApnaJob] = []
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
            except ApnaParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Apna records that failed to parse", len(issues), len(records)
            )
        return parsed, issues
