"""Parses a Careers24 advert's JSON-LD into a ``RawCareers24Job``.

Careers24 puts the ``JobPosting`` at the top level of its JSON-LD (unlike Built
In, which nests it under ``@graph``), so extraction is the simple case. The
interesting part is the salary, which is a **third** shape:

    Wellfound  {"value": {"minValue": ..., "maxValue": ..., "unitText": "YEAR"}}
    Built In   {"value": {"minValue": ..., "maxValue": ..., "unitText": "YEAR"}}
    Careers24  {"value": "650000", "unitText": "YEAR"}

A single scalar. :func:`_extract_salary` accepts all three, because writing it
for either of the first two would silently record no salary at all here -- and
silently is exactly the failure mode this project keeps hitting.

``unitText`` is mapped explicitly rather than passed through: the corpus
vocabulary is hourly/daily/weekly/monthly/yearly, and a value outside it
violates ``ck_job_salaries_pay_period``, whose violation aborts the enclosing
transaction.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.careers24.models import RawCareers24Job

from .exceptions import Careers24ParseError

#: schema.org ``unitText`` -> the corpus's pay_period vocabulary.
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


def _money(value: Any) -> float | None:
    """Coerce a schema.org monetary value to a float, or ``None``.

    The real payloads are plain digit strings (``"650000"``), but
    ``baseSalary`` is hand-entered on some postings and arrives formatted:
    ``"R 1 250 000,00"``, ``"$120,000"``, ``"1.250.000"``. The obvious
    implementation -- strip commas and the currency letter -- does **not** work
    on those: it leaves the internal spaces in and ``float()`` raises, and the
    caller has no way to tell a failed parse from a missing salary.

    The comma is genuinely ambiguous (``650,000`` is a thousand separator,
    ``650,00`` is European decimal). The rule used here is the standard one: a
    single comma with no dot, whose tail is not exactly three digits, is a
    decimal point. Anything else treats commas as thousands separators.

    Dots get the mirror treatment, because ``1.250.000`` cannot be a decimal.
    A single dot is left to ``float`` -- ``1.500`` is read as 1.5, which is the
    English convention and the only defensible default when the source does not
    say which it meant.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None
    # Drop currency symbols, ISO codes, and any other non-numeric decoration.
    text = re.sub(r"[^\d.,-]", "", text)
    if not text:
        return None

    if "," in text:
        if "." not in text and text.count(",") == 1 and len(text.rsplit(",", 1)[1]) != 3:
            text = text.replace(",", ".")  # decimal separator
        else:
            text = text.replace(",", "")  # thousands separator
    elif text.count(".") > 1:
        text = text.replace(".", "")  # "1.250.000" can only be thousands

    try:
        return float(text)
    except ValueError:
        return None


def _parse_ts(value: Any) -> date | None:
    """Parse "2026-10-15" or a full ISO timestamp."""
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


def _extract_salary(
    ld: dict,
) -> tuple[float | None, float | None, str | None, str | None, str | None, str]:
    """baseSalary -> (min, max, period, currency, unit, shape).

    Three shapes are in play, and which one a board emits is not guessable:

    * **Wellfound / Built In** -- ``{"value": {"minValue": ..., "maxValue": ...,
      "unitText": ...}}``. A real band.
    * **Careers24** -- ``{"value": {"@type": "QuantitativeValue",
      "value": "180", "unitText": "DAY"}}``. The scalar is nested one level
      deeper, under ``value.value``, and there is **no** ``minValue``/
      ``maxValue`` at all. A parser that handles only the range shape reads
      ``None`` for every bound here -- which is not an error, just a total
      silent loss of the salary on the half of the board that publishes one.
    * A bare ``{"value": "650000"}`` scalar, which the site has also been seen
      to emit.

    ``shape`` is kept in the raw payload so a future change in the site's
    markup is visible in the data rather than showing up as a quiet drop to
    zero salary rows.
    """
    salary = ld.get("baseSalary")
    if not isinstance(salary, dict):
        return None, None, None, None, None, "absent"
    currency = salary.get("currency") or None
    value = salary.get("value")

    def unit_of(*candidates: Any) -> str | None:
        for cand in candidates:
            if isinstance(cand, str) and cand.strip():
                return cand.strip().upper()
        return None

    # Range shape: {"value": {"minValue": ..., "maxValue": ..., "unitText": ...}}
    if isinstance(value, dict):
        if "minValue" in value or "maxValue" in value:
            unit = unit_of(value.get("unitText"), salary.get("unitText"))
            return (
                _money(value.get("minValue")),
                _money(value.get("maxValue")),
                _UNIT_TO_PERIOD.get(unit or ""),
                currency,
                unit,
                "range",
            )
        # Careers24's real shape: a QuantitativeValue holding a single scalar.
        # unitText is present but EMPTY on some postings (measured: 1 of the
        # first 4), which is why unit_of skips blanks rather than uppercasing
        # them into a truthy-looking "".
        unit = unit_of(value.get("unitText"), salary.get("unitText"))
        single = _money(value.get("value"))
        return single, single, _UNIT_TO_PERIOD.get(unit or ""), currency, unit, "quantitative"

    # Bare scalar shape.
    single = _money(value)
    unit = unit_of(salary.get("unitText"))
    return single, single, _UNIT_TO_PERIOD.get(unit or ""), currency, unit, "single"


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
    city = (address.get("addressLocality") or "").strip() or None
    region = (address.get("addressRegion") or "").strip() or None
    country = (address.get("addressCountry") or "").strip() or None

    # A posting with no street-level locality puts the *province* in
    # addressLocality, so city and region come out identical and a naive join
    # produces the label "Gauteng, Gauteng". Measured on the first 40 postings:
    # every province-only advert hit this. Emit each name once.
    parts: list[str] = []
    for part in (city, region):
        if part and part.casefold() not in {p.casefold() for p in parts}:
            parts.append(part)
    label = ", ".join(parts) if parts else country
    return (label or None), country, city, region


class Careers24Parser:
    """Turns a Careers24 JSON-LD block into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawCareers24Job:
        """Parse one advert.

        Raises:
            Careers24ParseError: No title. The id comes from the URL so it is
                always available, but a posting with no title is not a posting.
        """
        ld = extract_jsonld(html or "")
        title = (ld.get("title") or "").strip()
        if not title:
            raise Careers24ParseError(
                f"Careers24 advert {job_id} has no title; the page carried no "
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
        if declared and str(declared) != job_id:
            logger.warning(
                "careers24 id mismatch: URL says {} but JSON-LD identifier says {}",
                job_id,
                declared,
            )

        salary_min, salary_max, salary_period, currency, unit, shape = _extract_salary(ld)
        location, country, city, region = _extract_location(ld)

        return RawCareers24Job(
            source_job_id=str(job_id),
            title=title,
            company_name=(org.get("name") or "").strip() or "Unknown employer",
            industry=ld.get("industry") or None,
            employment_type=ld.get("employmentType") or None,
            location=location,
            country=country,
            city=city,
            region=region,
            description=ld.get("description") or None,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_period=salary_period,
            currency_iso_code=currency,
            posted_date=_parse_ts(ld.get("datePosted")),
            closing_date=_parse_ts(ld.get("validThrough")),
            url=url,
            listing_page=listing_page,
            raw={
                "salary_shape": shape,
                "unit_text": unit,
                "identifier_name": identifier.get("name"),
                "page_bytes": len(html or ""),
            },
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawCareers24Job], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawCareers24Job] = []
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
            except Careers24ParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Careers24 records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
