"""Parses a Wellfound posting's JSON-LD into a ``RawWellfoundJob``.

Every value comes from the schema.org ``JobPosting`` block that Wellfound puts
in each detail page. That block was measured on 2026-10-14 and carried 14 of 14
fields on all six postings sampled:

    title, identifier, employmentType, hiringOrganization (name, sameAs, logo
    and a per-office location array with coordinates), description, datePosted,
    jobLocation (with coordinates), baseSalary (currency, unitText,
    minValue/maxValue), jobBenefits, industry, directApply, image

Three traps, all measured rather than assumed:

  * ``identifier`` is a ``PropertyValue``, not a bare string: the id is at
    ``identifier.value`` and the *company* name is at ``identifier.name``.
    Reading ``identifier`` as a string yields ``{'@type': 'PropertyValue',
    'name': 'Checkr', 'value': '4839998'}`` -- a plausible-looking string that
    is neither an id nor a company.
  * ``baseSalary.value`` carries ``unitText`` ("YEAR"), not a schema pay period.
    "YEAR" is not in the corpus vocabulary (hourly/daily/weekly/monthly/yearly),
    and a wrong value violates ``ck_job_salaries_pay_period``, whose violation
    aborts the enclosing transaction.
  * ``hiringOrganization.location`` lists the *company's* offices while
    ``jobLocation`` lists where the *job* is. They are frequently different --
    the sampled Checkr role named Denver and San Francisco as offices and San
    Francisco as the job location -- so the two are kept apart.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.wellfound.models import RawWellfoundJob

from .exceptions import WellfoundParseError

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
    """Parse "2026-10-14T08:06:13Z" or "2026-10-14"."""
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


def extract_jsonld(html: str) -> dict:
    """Pull the schema.org JobPosting block out of a detail page.

    Returns an empty dict when the page has none. A missing block degrades the
    record rather than failing it, because the id from the URL is still a valid
    key and the listing told us the slug.
    """
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script[type='application/ld+json']"):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for c in candidates:
            if isinstance(c, dict) and c.get("@type") == "JobPosting":
                return c
    return {}


def _format_place(place: dict) -> tuple[str | None, str | None]:
    """One jobLocation entry -> (human string, country)."""
    address = place.get("address") or {}
    locality = (address.get("addressLocality") or "").strip()
    region = (address.get("addressRegion") or "").strip()
    country = (address.get("addressCountry") or "").strip() or None
    parts = [p for p in (locality, region) if p]
    label = ", ".join(parts) if parts else country
    return (label or None), country


def _leading_id(value: Any) -> str | None:
    """Leading digits of an ``identifier.value``, which is sometimes "<id>-<slug>"."""
    m = re.match(r"(\d{3,12})", str(value or ""))
    return m.group(1) if m else None


def _extract_salary(
    ld: dict,
) -> tuple[float | None, float | None, str | None, str | None, str | None]:
    """baseSalary -> (min, max, period, currency, unit_text).

    schema.org nests the numbers one level down, under
    ``baseSalary.value.QuantitativeValue``. Missing or wrongly-typed nodes
    yield None rather than raising, because a posting without salary is still
    a posting.
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


def _extract_locations(ld: dict) -> tuple[list[str], list[str]]:
    """jobLocation -> (labels, countries), de-duplicated, order preserved.

    A single dict is accepted as well as a list: schema.org permits both, and
    Wellfound used a list on every posting measured but that is not contractual.
    """
    raw_locations = ld.get("jobLocation")
    if isinstance(raw_locations, dict):
        raw_locations = [raw_locations]
    labels: list[str] = []
    countries: list[str] = []
    for place in raw_locations or []:
        if not isinstance(place, dict):
            continue
        label, country = _format_place(place)
        if label and label not in labels:
            labels.append(label)
        if country and country not in countries:
            countries.append(country)
    return labels, countries


class WellfoundParser:
    """Turns a Wellfound JSON-LD block into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_path: str | None = None,
    ) -> RawWellfoundJob:
        """Parse one posting.

        Raises:
            WellfoundParseError: No title. The id is taken from the URL so it is
                always available, but a posting with no title is not a posting.
        """
        ld = extract_jsonld(html or "")
        title = (ld.get("title") or "").strip()
        if not title:
            raise WellfoundParseError(
                f"Wellfound posting {job_id} has no title; the page carried no "
                "JobPosting JSON-LD title (an empty block means the markup changed)"
            )

        org = ld.get("hiringOrganization") or {}
        if not isinstance(org, dict):
            org = {}

        salary_min, salary_max, salary_period, currency, unit = _extract_salary(ld)
        locations, countries = _extract_locations(ld)

        # identifier is a PropertyValue: name=company, value=the id. Measured
        # 2026-10-14: `value` is a bare numeric id on most postings but
        # "<id>-<slug>" on others (e.g. "3246477-group-product-manager-ai-
        # native-data-warehouse"), so only the leading digits are compared.
        # The URL id is authoritative either way -- it is what the listing
        # linked and what dedup keys on.
        identifier = ld.get("identifier") or {}
        declared_id = identifier.get("value") if isinstance(identifier, dict) else None
        declared_prefix = _leading_id(declared_id)
        if declared_id and declared_prefix and declared_prefix != job_id:
            logger.warning(
                "wellfound id mismatch: URL says {} but JSON-LD identifier says {}",
                job_id,
                declared_id,
            )

        logo = org.get("logo") or ld.get("image") or None

        return RawWellfoundJob(
            source_job_id=str(job_id),
            title=title,
            company_name=(org.get("name") or "").strip() or "Unknown employer",
            company_website=org.get("sameAs") or None,
            company_logo_url=logo,
            employment_type=ld.get("employmentType") or None,
            industry=ld.get("industry") or None,
            locations=locations,
            location_countries=countries,
            organization_locations=(
                org.get("location") if isinstance(org.get("location"), list) else []
            ),
            description=ld.get("description") or None,
            benefits=ld.get("jobBenefits") or None,
            direct_apply=ld.get("directApply"),
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
                "identifier_name": identifier.get("name") if isinstance(identifier, dict) else None,
                "page_bytes": len(html or ""),
            },
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawWellfoundJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawWellfoundJob] = []
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
            except WellfoundParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Wellfound records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues


def _to_datetime(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime(value.year, value.month, value.day)
