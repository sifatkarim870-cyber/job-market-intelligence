"""Parses a Nationale Vacaturebank ad page into a ``RawNationaleVacaturebankNlJob``.

The ad page carries a schema.org ``JobPosting`` block with nearly every field
this platform needs, so the parser is mostly a careful mapping rather than
markup extraction. Measured on 2026-11-22::

    <script type="application/ld+json">
    {"@type": "JobPosting", "title": "Back office support",
     "hiringOrganization": {"@type": "Organization", "name": "Michael Page"},
     "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress",
        "addressLocality": "Rotterdam", "addressRegion": "Zuid-Holland",
        "addressCountry": "NL", "postalCode": "3011"}},
     "datePosted": "2026-11-03T23:00:00Z",
     "validThrough": "2027-01-02T23:00:00Z",
     "employmentType": ["FULL_TIME", "PART_TIME"],
     "baseSalary": {"@type": "MonetaryAmount", "currency": "EUR",
        "value": {"minValue": 3000, "maxValue": 3700, "unitText": "MONTH"}},
     "description": "<p>...</p>"}
    </script>

The traps:

* ``datePosted``/``validThrough`` are stamped at ``22:00Z``/``23:00Z`` --
  midnight in the Netherlands -- so they are converted to Europe/Amsterdam
  before the date is taken.
* ``employmentType`` is a string or a list; ``["FULL_TIME", "PART_TIME"]`` is
  the board's "either" default and is preserved verbatim for the cleaner.
* ``baseSalary`` is the ad's own offer. A second ``Occupation`` block carries
  the board's market ``estimatedSalary``; it is kept in ``raw`` for audit but
  never mapped to salary fields.
* ``baseSalary.value.unitText`` is **not trustworthy when it says MONTH**: the
  board stamps an hourly rate with ``"MONTH"`` (a "bruto uurloon van EUR 18,43
  - 23,99" ad shipped ``23`` with ``unitText: "MONTH"``). An amount far too
  small for a month is therefore re-read as hourly and flagged -- see
  ``_salary``.
* Withdrawn ads (HTTP 410, or a 200 with no ``JobPosting`` block) are dropped
  by the client before parsing; if one reaches here it raises a clear error.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.html_scraper.jsonld import json_ld_job_posting

from .exceptions import NationaleVacaturebankNlParseError
from .models import RawNationaleVacaturebankNlJob

_NL_TZ = ZoneInfo("Europe/Amsterdam")

#: An amount labelled ``unitText: "MONTH"`` below this many EUR cannot be a
#: month on this board (genuine monthly ads sample at EUR 2,000-8,500). It is
#: instead read as an hourly rate -- see ``_salary`` for the measured evidence.
_IMPLAUSIBLE_MONTHLY_FLOOR_EUR = 500.0

#: schema.org ``QuantitativeValue.unitText`` -> ``pay_period`` vocabulary.
_PERIOD_BY_UNIT: dict[str, str] = {
    "HOUR": "hourly",
    "HOURLY": "hourly",
    "DAY": "daily",
    "DAILY": "daily",
    "WEEK": "weekly",
    "WEEKLY": "weekly",
    "MONTH": "monthly",
    "MONTHLY": "monthly",
    "YEAR": "yearly",
    "ANNUAL": "yearly",
    "ANNUALLY": "yearly",
}


def _to_nl_date(value: Any) -> date | None:
    """Parse an ISO timestamp and take its date in Europe/Amsterdam."""
    if not value:
        return None
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, date):
        return value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
    if stamp.tzinfo is None:
        return stamp.date()
    return stamp.astimezone(_NL_TZ).date()


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return round(number, 2) if number > 0 else None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def _first_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _text(value: Any) -> str | None:
    """A schema.org value that may be a string, a dict with ``name``, or a list."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        return _text(value.get("name"))
    if isinstance(value, list):
        for item in value:
            text = _text(item)
            if text:
                return text
    return None


def _employment_types(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        return []
    seen: list[str] = []
    for item in values:
        text = _text(item)
        if text:
            token = text.upper().replace(" ", "_")
            if token not in seen:
                seen.append(token)
    return seen


def _logo_url(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        url = value.get("url") or value.get("contentUrl")
        return str(url).strip() if url else None
    if isinstance(value, list):
        for item in value:
            url = _logo_url(item)
            if url:
                return url
    return None


def _salary(
    job: dict[str, Any],
) -> tuple[str | None, float | None, float | None, str | None, str | None, bool]:
    """Return ``(currency, min, max, period, unit_raw, period_assumed)``."""
    block = _first_dict(job.get("baseSalary"))
    if not block:
        return "EUR", None, None, None, None, False

    currency = _text(block.get("currency")) or "EUR"
    value = block.get("value")
    if isinstance(value, dict):
        low = _as_float(value.get("minValue"))
        high = _as_float(value.get("maxValue"))
        unit = _text(value.get("unitText"))
    else:
        low = high = _as_float(value)
        unit = _text(block.get("unitText"))

    if low is None and high is None:
        return currency, None, None, None, unit, False
    if low is None:
        low = high
    if high is None:
        high = low
    if low is not None and high is not None and low > high:
        low, high = high, low

    period = _PERIOD_BY_UNIT.get((unit or "").upper())
    assumed = False
    if period is None and (low is not None or high is not None):
        # An amount with no ``unitText`` at all: Dutch boards quote monthly, so
        # it is assumed monthly -- unless the magnitude itself is impossible for
        # a month (see the hourly-rate trap below), in which case hourly is the
        # only reading that fits. Either way the assumption is recorded.
        if high is not None and high < _IMPLAUSIBLE_MONTHLY_FLOOR_EUR:
            period = "hourly"
        else:
            period = "monthly"
        assumed = True
    elif period == "monthly" and high is not None and high < _IMPLAUSIBLE_MONTHLY_FLOOR_EUR:
        # The hourly-rate trap, measured on 2026-11-22. The board publishes an
        # ad's hourly rate in ``baseSalary`` but stamps ``unitText: "MONTH"`` on
        # it. Three ads pinned at the same time:
        #
        #   * "Medewerker klantenservice" -- body says "bruto uurloon van
        #     EUR 18,43 - 23,99", JSON-LD says minValue/maxValue 23, unit MONTH;
        #   * "Logistiek Assistent" -- "EUR 14,71 bruto per uur", JSON-LD 14 MONTH;
        #   * "Devops Engineer (Linux)" -- "Maximaal EUR 80 per uur", JSON-LD 80 MONTH.
        #
        # A genuine monthly figure on the same board is >= ~2,000 (a sampled
        # monthly ad read 3,198 - 4,779), so an amount under a few hundred
        # cannot be a month. Re-reading it as hourly is the only defensible
        # interpretation; the raw unit stays in ``salary_unit_raw`` and the
        # decision is flagged rather than hidden.
        period = "hourly"
        assumed = True
    return currency, low, high, period, unit, assumed


def _occupation_block(html: str) -> dict[str, Any] | None:
    """Return the page's ``Occupation`` block (market salary estimate)."""
    soup = BeautifulSoup(html or "", "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for item in candidates:
            if isinstance(item, dict) and item.get("@type") == "Occupation":
                return item
    return None


def parse_detail(
    job_id: str,
    html: str,
    url: str | None = None,
    listing_category: str | None = None,
) -> RawNationaleVacaturebankNlJob:
    """Parse one ad page's ``JobPosting`` block."""
    job = json_ld_job_posting(html or "")
    if job is None:
        raise NationaleVacaturebankNlParseError(
            f"Nationale Vacaturebank ad {job_id} has no schema.org JobPosting "
            "block. The ad is withdrawn or the page markup changed."
        )

    soup = BeautifulSoup(html or "", "html.parser")
    title = _text(job.get("title"))
    if not title:
        heading = soup.find("h1")
        title = heading.get_text(" ", strip=True) if heading else None
    if not title:
        raise NationaleVacaturebankNlParseError(
            f"Nationale Vacaturebank ad {job_id} has no title in its JobPosting block or <h1>."
        )

    hiring = _first_dict(job.get("hiringOrganization"))
    location = _first_dict(job.get("jobLocation"))
    address = _first_dict(location.get("address"))

    education_block = _first_dict(job.get("educationRequirements"))
    experience_block = _first_dict(job.get("experienceRequirements"))

    currency, salary_min, salary_max, salary_period, unit_raw, assumed = _salary(job)
    occupation = _occupation_block(html or "")

    country = _text(address.get("addressCountry"))
    if country and len(country) == 2:
        country = {"NL": "Netherlands"}.get(country.upper(), country)

    return RawNationaleVacaturebankNlJob(
        source_job_id=str(job_id),
        title=title,
        company_name=_text(hiring.get("name")) or "Unknown employer",
        company_logo_url=_logo_url(hiring.get("logo")),
        location_text=_text(address.get("addressLocality")),
        region=_text(address.get("addressRegion")),
        country=country or "Netherlands",
        postal_code=_text(address.get("postalCode")),
        latitude=_as_float(location.get("latitude")),
        longitude=_as_float(location.get("longitude")),
        description_html=job.get("description"),
        posted_date=_to_nl_date(job.get("datePosted")),
        closing_date=_to_nl_date(job.get("validThrough")),
        employment_types=_employment_types(job.get("employmentType")),
        work_hours=_text(job.get("workHours")),
        education_credential=_text(education_block.get("credentialCategory")),
        experience_months=_as_int(experience_block.get("monthsOfExperience")),
        occupational_category=_text(job.get("occupationalCategory")),
        industry=_text(job.get("industry")),
        job_location_type=_text(job.get("jobLocationType")),
        direct_apply=job.get("directApply") if isinstance(job.get("directApply"), bool) else None,
        salary_currency=currency,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_period=salary_period,
        salary_unit_raw=unit_raw,
        salary_period_assumed=assumed,
        estimated_salary=occupation.get("estimatedSalary") if occupation else None,
        job_url=url,
        listing_category=listing_category,
        raw={
            "job_posting": job,
            "occupation": occupation,
            "page_bytes": len(html or ""),
            "title_tag": soup.title.get_text(" ", strip=True) if soup.title else None,
        },
    )


class NationaleVacaturebankNlParser:
    """Turns a Nationale Vacaturebank ad page into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_category: str | None = None,
    ) -> RawNationaleVacaturebankNlJob:
        return parse_detail(job_id, html or "", url=url, listing_category=listing_category)

    def parse_many(
        self, records: list[dict]
    ) -> tuple[list[RawNationaleVacaturebankNlJob], list[str]]:
        parsed: list[RawNationaleVacaturebankNlJob] = []
        issues: list[str] = []
        for rec in records:
            try:
                parsed.append(
                    self.parse(
                        str(rec.get("job_id") or ""),
                        rec.get("html"),
                        url=rec.get("url"),
                        listing_category=rec.get("listing_category"),
                    )
                )
            except NationaleVacaturebankNlParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Nationale Vacaturebank records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
