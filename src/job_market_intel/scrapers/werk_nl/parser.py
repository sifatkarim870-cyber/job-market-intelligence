"""Parser for UWV Werk.nl (werk.nl) vacancy documents.

The list item and the detail document together carry one vacancy. Measured
shapes (2026-11-28):

* Search item (``POST .../api/search``) --
  ``{key, referenceNumber, score, resultDepth, internalReferenceNumber,
  profession, vacatureTitle, modified, organisation, workLocationCity,
  workLocationType, workLocationForeignCountry, workLocationForeignCity,
  minHours, maxHours, contractType, studyLevel, distance, leerbaan,
  stageplaats}``. ``modified`` is ``"YYYY-MM-DD HH:MM:SS"``.
* Detail (``GET .../api/vacature/{referenceNumber}``) --
  ``{referenceNumber, title, expirationDate, modifiedDate, createdDate,
  proposition: {termsOfEmploymentDescription, workLocation: {type,
  countryCode, postcode, city}, function: {code, name, description,
  customDescription}, salary: {type, amountIndication}, contract: {type,
  startDate, endDate}, workhours: {minimumHours, maximumHours, werktijden}},
  employer: {organizationName, website, sector, addressNetherlands},
  applicationMethods: [{sollicitatieWijze, urlApplicationForm}], ...}``.
  The body is ``proposition.function.description``; ``description`` at the
  top level is usually ``null``.

The salary is a free-text ``amountIndication`` (``null`` on most ads, a plain
``"5000"`` on some), so anything numeric in it is read as a EUR amount and the
period is taken from the words around it (``uur``/``maand``/``jaar``), else
assumed monthly. Nothing is invented: an empty indication stays undisclosed.

Contract type is the board's own ``Vast`` / ``Mogelijk vast`` / ``Tijdelijk``.
``Tijdelijk`` maps onto ``temporary``; ``Vast`` (permanent) has no matching
code in this schema, so it stays ``None`` and the raw value is kept.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from job_market_intel.cleaning.common import CleanedJob

from .exceptions import WerkNlParseError
from .models import RawWerkNlJob

#: The board's "Soort contract" string -> ``ref.employment_types.code``.
#: ``Vast`` (permanent) has no equivalent code, so it maps to ``None`` rather
#: than a guessed ``full_time``.
_CONTRACT_TYPES: dict[str, str] = {
    "tijdelijk": "temporary",
}

#: Period words -> ``salary.job_salaries.pay_period`` CHECK values.
_PERIOD_HINTS: tuple[tuple[str, str], ...] = (
    ("per uur", "hourly"),
    ("/uur", "hourly"),
    ("p/u", "hourly"),
    ("uur", "hourly"),
    ("hour", "hourly"),
    ("per dag", "daily"),
    ("dag", "daily"),
    ("per week", "weekly"),
    ("week", "weekly"),
    ("per maand", "monthly"),
    ("p/m", "monthly"),
    ("maand", "monthly"),
    ("month", "monthly"),
    ("per jaar", "yearly"),
    ("jaar", "yearly"),
    ("year", "yearly"),
    ("annual", "yearly"),
)

_NUMBER = re.compile(r"\d[\d.,]*")


def clean_text(value: Any) -> str:
    """Unescape entities and collapse whitespace."""
    if value is None:
        return ""
    return " ".join(html.unescape(str(value)).split()).strip()


def parse_amount(token: str) -> float | None:
    """Parse one Dutch-formatted amount (``"3.500,50"`` -> 3500.5)."""
    text = token.replace("\u00a0", " ").strip()
    digits = re.sub(r"[^0-9,.]", "", text)
    if not digits:
        return None
    if "," in digits and "." in digits:
        # Whichever separator comes last is the decimal one.
        if digits.rfind(",") > digits.rfind("."):
            digits = digits.replace(".", "").replace(",", ".")
        else:
            digits = digits.replace(",", "")
    elif "," in digits:
        head, _, tail = digits.rpartition(",")
        digits = head.replace(",", "") + ("." if len(tail) != 3 else "") + tail
    elif "." in digits:
        head, _, tail = digits.rpartition(".")
        digits = head.replace(".", "") + ("." if len(tail) != 3 else "") + tail
    try:
        amount = float(digits)
    except ValueError:
        return None
    return amount if amount > 0 else None


def parse_salary_indication(
    text: Any,
) -> tuple[float | None, float | None, str, bool]:
    """Return ``(min, max, pay_period, disclosed)`` from a free-text indication.

    A single number is stored as ``salary_min`` only; the indication does not
    say it is a range, and inventing a maximum would be a claim the ad did not
    make.
    """
    raw = clean_text(text)
    if not raw:
        return None, None, "monthly", False

    low = raw.lower()
    pay_period = "monthly"
    for needle, period in _PERIOD_HINTS:
        if needle in low:
            pay_period = period
            break

    amounts = [
        amount for token in _NUMBER.findall(raw) if (amount := parse_amount(token)) is not None
    ]
    if not amounts:
        return None, None, pay_period, False

    is_range = bool(re.search(r"\d[\d.,]*\s*(?:[-–]|tot|t/m)\s*(?:€|eur|\\$)?\s*\d", raw, re.I))
    if is_range and len(amounts) >= 2:
        low_amount, high_amount = sorted(amounts[:2])
        return low_amount, high_amount, pay_period, True
    return amounts[0], None, pay_period, True


def parse_date(value: Any) -> datetime | None:
    """Parse the ISO-ish date shapes the API writes into naive datetimes."""
    text = clean_text(value)
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None
    return parsed.replace(tzinfo=None)


def normalize_description(raw: Any) -> str:
    """Decode entities, strip inline HTML, and collapse blank lines."""
    if raw is None:
        return ""
    text = html.unescape(str(raw))
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text("\n", strip=True)
    text = html.unescape(text).replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def map_employment_type(raw: Any) -> str | None:
    """Map the board's contract type onto one ``ref.employment_types.code``."""
    text = clean_text(raw).lower()
    return _CONTRACT_TYPES.get(text)


def _location_parts(raw: RawWerkNlJob) -> dict[str, str]:
    """Read the city and country from the detail, falling back to the list item."""
    detail = raw.detail or {}
    proposition = detail.get("proposition") or {}
    work_location = proposition.get("workLocation") or {}
    item = raw.list_item

    city = (
        clean_text(work_location.get("city"))
        or clean_text(item.get("workLocationCity"))
        or clean_text(item.get("workLocationForeignCity"))
    )
    country_code = clean_text(work_location.get("countryCode")).upper()
    foreign_country = clean_text(item.get("workLocationForeignCountry"))
    country = country_code or foreign_country.upper() or "NL"

    return {
        "city": city,
        "country": country,
        "postcode": clean_text(work_location.get("postcode")),
    }


def build_location(parts: dict[str, str]) -> str:
    """Compose ``"<city>; <country>"``; the country is an ISO-2 token."""
    city = parts.get("city", "")
    country = parts.get("country") or "NL"
    if not city:
        return country
    if city.lower() == country.lower():
        return country
    return f"{city}; {country}"


def _structured_summary(item: dict[str, Any], proposition: dict[str, Any]) -> str:
    """A labelled, non-invented summary for a vacancy with no body text."""
    function = proposition.get("function") or {}
    lines = ["Vacature gepubliceerd op werk.nl (UWV)."]
    for label, value in (
        ("Functie", function.get("name")),
        ("Beroep", item.get("profession")),
        ("Organisatie", item.get("organisation")),
        ("Plaats", item.get("workLocationCity")),
        ("Contract", item.get("contractType")),
        ("Opleiding", item.get("studyLevel")),
    ):
        text = clean_text(value)
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


def _apply_url(detail: dict[str, Any], fallback: str) -> str:
    """The employer's own application URL when present, else the ad URL."""
    for method in detail.get("applicationMethods") or []:
        if not isinstance(method, dict):
            continue
        url = clean_text(method.get("urlApplicationForm"))
        if url.lower().startswith(("http://", "https://")):
            return url
    return fallback


class WerkNlParser:
    """Turns one Werk.nl list item + detail into a validated ``CleanedJob``."""

    def parse_job(self, raw: RawWerkNlJob) -> CleanedJob:
        """Parse one vacancy into a ``CleanedJob``."""
        item = raw.list_item
        detail = raw.detail or {}
        proposition = detail.get("proposition") or {}
        function = proposition.get("function") or {}
        employer = detail.get("employer") or {}

        title = clean_text(detail.get("title")) or clean_text(item.get("vacatureTitle"))
        if not title:
            raise WerkNlParseError(f"no title in Werk.nl vacancy {raw.job_id} ({raw.url})")

        company = (
            clean_text(employer.get("organizationName"))
            or clean_text(item.get("organisation"))
            or "Confidential Employer"
        )

        parts = _location_parts(raw)
        location = build_location(parts)

        body = (
            normalize_description(function.get("description"))
            or normalize_description(function.get("customDescription"))
            or normalize_description(proposition.get("termsOfEmploymentDescription"))
            or normalize_description(detail.get("description"))
        )
        # Many ads carry only a job label ("Schilder", "Magazijnmedewerker") in
        # the description field -- 53 of the first 300 rows were under ten
        # words. A one-word body is not a description and scores as if it were,
        # so below five words the labelled summary (function, profession,
        # organisation, place, contract, education) is stored instead. This is
        # the same threshold Empleate.es uses.
        if len(body.split()) >= 5:
            description_source = "proposition.function.description"
        else:
            body = _structured_summary(item, proposition)
            description_source = "structured_summary"

        salary = proposition.get("salary") or {}
        salary_min, salary_max, pay_period, salary_disclosed = parse_salary_indication(
            salary.get("amountIndication")
        )

        posting_date = parse_date(detail.get("createdDate")) or parse_date(item.get("modified"))
        closing_date = parse_date(detail.get("expirationDate"))
        if posting_date and closing_date and closing_date < posting_date:
            closing_date = None

        contract_type = clean_text(item.get("contractType"))
        employment_code = map_employment_type(contract_type)

        words = len(body.split())
        score = 0.4
        score += 0.2 if words >= 60 else (0.1 if words >= 20 else 0.0)
        score += 0.1 if company != "Confidential Employer" else 0.0
        score += 0.1 if location != "NL" else 0.0
        score += 0.1 if salary_disclosed else 0.0
        score += 0.05 if posting_date else 0.0
        if description_source == "structured_summary":
            score = min(score, 0.6)

        raw_payload = {
            "url": raw.url,
            "list_position": raw.list_position,
            "list_total": raw.list_total,
            "description_source": description_source,
            "description_chars": len(body),
            "contract_type": contract_type,
            "work_location_type": item.get("workLocationType"),
            "study_level": item.get("studyLevel"),
            "min_hours": item.get("minHours"),
            "max_hours": item.get("maxHours"),
            "location_parts": parts,
            "salary_indication": salary.get("amountIndication"),
            "list_item": item,
            "detail": detail or None,
        }

        return CleanedJob(
            source_job_id=raw.job_id,
            job_title=title,
            company_name=company,
            company_logo_url=None,
            skills=[],
            location_cleaned=location,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=body or None,
            word_count=words,
            apply_url=_apply_url(detail, raw.url),
            original_url=raw.url,
            posting_date=posting_date,
            closing_date=closing_date,
            data_quality_score=round(min(score, 0.95), 2),
            raw_payload=raw_payload,
            currency_iso_code="EUR",
            pay_period=pay_period,
            employment_type_code=employment_code,
            remote_work_type_code=None,
        )

    def parse_jobs(self, raw_jobs: list[RawWerkNlJob]) -> list[CleanedJob]:
        """Parse a batch, skipping and logging individual failures."""
        from loguru import logger

        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.parse_job(raw))
            except WerkNlParseError as exc:
                logger.warning("Skipping Werk.nl vacancy {}: {}", raw.job_id, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Unexpected parse error for Werk.nl vacancy {}: {}",
                    raw.job_id,
                    exc,
                )
        return cleaned
