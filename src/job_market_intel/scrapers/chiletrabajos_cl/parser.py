"""Parser for Chiletrabajos (chiletrabajos.cl) ad pages.

Every ad page carries three Schema.org JSON-LD blocks: a ``BreadcrumbList``,
the ``JobPosting`` this module reads, and an ``ItemList`` of related ads.
The ``JobPosting`` block was measured on archived pages from 2026-05..2026-11
and has these shapes:

* ``baseSalary`` is a ``MonetaryAmount`` whose ``value`` is a
  ``QuantitativeValue`` with a **capitalised** ``Value`` key (``"1570000"``)
  or an integer ``0``. ``0`` means "salary not published", not "zero pesos".
* ``datePosted`` is ``"YYYY-MM-DD HH:MM:SS"`` (a space, not ``T``);
  ``validThrough`` is the ISO-8601 ``"YYYY-MM-DDTHH:MM:SS"``.
* ``hiringOrganization`` is ``{name, logo}``; ``logo`` is often ``""``.
* ``jobLocation.address`` is ``{"addressLocality": "<comuna>",
  "addressRegion": "<ISO 3166-2:CL code>", "addressCountry": "CL",
  "postalCode": <int>}``. The region is a **two-letter ISO code**
  (``AT`` Atacama, ``AN`` Antofagasta, ``LL`` Los Lagos, ``LI`` O'Higgins,
  ``RM`` Metropolitana, ``BI`` Biobío measured), not a name, so it is mapped
  onto the full name this project seeds in ``ref.regions``.
* ``employmentType`` is one Schema.org code (``FULL_TIME``, ``PART_TIME``)
  or a comma-joined pair (``"PART_TIME, FULL_TIME"``).
* ``description`` is a plain string with ``\\r\\n`` line breaks and HTML
  entities (``&quot;``); some bodies also carry real inline HTML.

The board publishes no remote field, so ``remote_work_type_code`` is set only
when the block itself says ``jobLocationType: TELECOMMUTE``; nothing is
inferred from prose.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.cleaning.common import CleanedJob

from .exceptions import ChiletrabajosClParseError
from .models import RawChiletrabajosJob

#: ISO 3166-2:CL code -> the region name seeded in ``ref.regions``.
#: The resolver matches ``region_name`` exactly, so this table and
#: ``seed/regions.py`` must stay byte-identical.
_REGION_BY_CODE: dict[str, str] = {
    "AP": "Arica y Parinacota",
    "TA": "Tarapacá",
    "AN": "Antofagasta",
    "AT": "Atacama",
    "CO": "Coquimbo",
    "VS": "Valparaíso",
    "RM": "Metropolitana de Santiago",
    "LI": "O'Higgins",
    "ML": "Maule",
    "NB": "Ñuble",
    "BI": "Biobío",
    "AR": "La Araucanía",
    "LR": "Los Ríos",
    "LL": "Los Lagos",
    "AI": "Aysén",
    "MA": "Magallanes",
}

#: Schema.org employment type -> ``ref.employment_types.code``. ``VOLUNTEER``,
#: ``PER_DIEM`` and ``OTHER`` have no equivalent in this schema and map to
#: ``None`` rather than a guess; the raw value stays in ``raw_payload``.
_EMPLOYMENT_TYPES: dict[str, str] = {
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACTOR": "contract",
    "CONTRACT": "contract",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "FREELANCE": "freelance",
    "APPRENTICESHIP": "apprenticeship",
}

#: ``unitText`` -> ``salary.job_salaries.pay_period`` CHECK values.
_PAY_PERIODS: dict[str, str] = {
    "HOUR": "hourly",
    "DAY": "daily",
    "WEEK": "weekly",
    "MONTH": "monthly",
    "YEAR": "yearly",
    "ANNUAL": "yearly",
}

_COUNTRY_ALIASES = {
    "CHILE": "CL",
    "CL": "CL",
}


def clean_text(value: Any) -> str:
    """Unescape entities and collapse whitespace."""
    if value is None:
        return ""
    return " ".join(html.unescape(str(value)).split()).strip()


def parse_salary_amount(value: Any) -> float | None:
    """Parse a Chilean-formatted salary into a positive float.

    CLP amounts are normally plain integers (``"1570000"`` or ``1570000``),
    but thousands separators are handled too: ``"1.570.000"`` is 1,570,000,
    while ``"1.570,50"`` is 1,570.50. ``0`` means "not published", not
    "zero pesos".
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    text = str(value).replace("\u00a0", " ").strip()
    if not text:
        return None
    digits = re.sub(r"[^0-9,.\-]", "", text)
    if not digits or digits in {"-", ".", ","}:
        return None
    if "," in digits and "." in digits:
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


def _salary_number(value: Any) -> float | None:
    """Read one salary bound, including ``{"@type": ..., "value": n}`` shapes."""
    if isinstance(value, dict):
        for key in ("Value", "value", "amount"):
            if key in value:
                return parse_salary_amount(value[key])
        return None
    return parse_salary_amount(value)


def parse_salary(json_ld: dict[str, Any]) -> tuple[float | None, float | None, str, str, bool]:
    """Return ``(min, max, currency, pay_period, disclosed)`` for one ad.

    A single published amount is stored as ``salary_min`` only; the schema
    does not say it is a range, and inventing a maximum would be a claim the
    ad did not make.
    """
    currency = "CLP"
    pay_period = "monthly"
    base_salary = json_ld.get("baseSalary")
    if not isinstance(base_salary, dict):
        return None, None, currency, pay_period, False

    if base_salary.get("currency"):
        currency = str(base_salary["currency"]).strip().upper()
    value = base_salary.get("value")
    if not isinstance(value, dict):
        amount = _salary_number(value)
        return (
            (amount, None, currency, pay_period, amount is not None)
            if amount
            else (
                None,
                None,
                currency,
                pay_period,
                False,
            )
        )

    unit = str(value.get("unitText") or "").strip().upper()
    for needle, period in _PAY_PERIODS.items():
        if needle in unit:
            pay_period = period
            break

    minimum = _salary_number(value.get("minValue"))
    maximum = _salary_number(value.get("maxValue"))
    if minimum is None:
        minimum = _salary_number(value.get("Value"))
    if minimum is None:
        minimum = _salary_number(value.get("value"))
    if minimum is None and maximum is None:
        return None, None, currency, pay_period, False
    if minimum is not None and maximum is not None and maximum < minimum:
        minimum, maximum = maximum, minimum
    return minimum, maximum, currency, pay_period, True


def map_employment_type(raw: Any) -> str | None:
    """Map a Schema.org ``employmentType`` onto one code, or ``None``.

    The board writes a comma-joined pair (``"PART_TIME, FULL_TIME"``) when
    both hours are open; that is two different codes, so it is stored as
    ``None`` instead of picking one. The raw value is kept in ``raw_payload``.
    """
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        values = [str(item) for item in raw]
    else:
        values = re.split(r"[,/;|]", str(raw))
    codes: list[str] = []
    for value in values:
        code = _EMPLOYMENT_TYPES.get(value.strip().upper())
        if code and code not in codes:
            codes.append(code)
    return codes[0] if len(codes) == 1 else None


def _region_text(raw: Any) -> str | None:
    """Flatten a region value (string, ``AdministrativeArea`` object or list)."""
    if isinstance(raw, (list, tuple)):
        for item in raw:
            text = _region_text(item)
            if text:
                return text
        return None
    if isinstance(raw, dict):
        for key in ("name", "alternateName", "@id"):
            candidate = raw.get(key)
            if candidate:
                return _region_text(candidate)
        return None
    text = clean_text(raw)
    return text or None


def map_region_code(raw: Any) -> str | None:
    """Map ``addressRegion`` (ISO 3166-2:CL code) onto a seeded region name.

    ``CL-AT`` and ``at`` both normalise to ``AT``. A value that is not one of
    the sixteen codes is returned as-is only when it looks like a place name
    (more than three letters and not a bare code); otherwise it is dropped so
    an unknown code cannot become a bogus ``ref.regions`` name.

    ``addressRegion`` is a string on every page measured, but Schema.org also
    allows a nested ``AdministrativeArea`` object or a list, so those shapes
    are unwrapped rather than stringified into a bogus name.
    """
    text = _region_text(raw)
    if not text:
        return None
    code = text.upper()
    if code.startswith("CL-"):
        code = code[3:]
    if code in _REGION_BY_CODE:
        return _REGION_BY_CODE[code]
    if len(code) <= 3 and code.isalpha():
        return None
    return text


def _address_part(value: Any) -> str:
    """Read one ``PostalAddress`` value that may be a string or a dict."""
    if isinstance(value, dict):
        for key in ("name", "addressLocality", "addressRegion", "addressCountry"):
            if value.get(key):
                return clean_text(value[key])
        return ""
    return clean_text(value)


def build_location(address: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """Compose ``"<comuna>; <region>; CL"`` and return the raw parts.

    The city is the board's ``addressLocality``; keeping it means a seeded
    comuna resolves at city level and an unseeded one still resolves at
    region level. The country segment is the ISO-2 code ``CL`` so the
    resolver cannot confuse it with a place name.
    """
    city = _address_part(address.get("addressLocality"))
    region = map_region_code(address.get("addressRegion"))
    country_raw = _address_part(address.get("addressCountry"))
    country = _COUNTRY_ALIASES.get(country_raw.upper(), "CL" if not country_raw else country_raw)

    parts: list[str] = []
    seen: set[str] = set()
    for part in (city, region, country):
        if not part:
            continue
        key = part.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(part)
    return ("; ".join(parts) if parts else "CL"), {
        "city": city,
        "region": region or "",
        "country_raw": country_raw,
        "country_iso2": country,
    }


def parse_date(value: Any) -> datetime | None:
    """Parse the two date shapes the board writes into naive UTC datetimes."""
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
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text("\n", strip=True)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_identifier(json_ld: dict[str, Any], fallback: str) -> str:
    """Use a publisher-supplied ``identifier`` when present, else the URL id."""
    identifier = json_ld.get("identifier")
    value: Any = None
    if isinstance(identifier, dict):
        value = identifier.get("value")
    elif isinstance(identifier, (str, int)):
        value = identifier
    text = clean_text(value)
    return text or fallback


def _repair_description_field(content: str) -> str:
    """Drop only the ``description`` field from a JSON-LD block.

    The Chile board was not observed emitting the unescaped-quote defect that
    the AfricaWork boards do, but the repair is cheap and keeps one malformed
    ad from losing the other twenty fields. Two patterns are tried because the
    key after ``description`` is not guaranteed.
    """
    repaired = re.sub(
        r'"description"\s*:\s*".*?"\s*,\s*"(?=[A-Za-z@])',
        '"',
        content,
        flags=re.DOTALL,
    )
    if repaired != content:
        return repaired
    return re.sub(
        r'"description"\s*:\s*".*?"\s*,\s*(?=")',
        "",
        content,
        flags=re.DOTALL,
    )


def _iter_ld_items(data: Any):
    """Yield every dict in a JSON-LD document, including ``@graph`` members."""
    if isinstance(data, list):
        for item in data:
            yield from _iter_ld_items(item)
    elif isinstance(data, dict):
        yield data
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_ld_items(item)


def extract_job_posting(soup: BeautifulSoup) -> dict[str, Any]:
    """Find and parse the Schema.org ``JobPosting`` block."""
    for script in soup.find_all("script", type="application/ld+json"):
        content = (script.string or script.text or "").strip()
        if not content:
            continue
        for candidate in (content, _repair_description_field(content)):
            try:
                data = json.loads(candidate, strict=False)
            except (json.JSONDecodeError, ValueError):
                continue
            for item in _iter_ld_items(data):
                if str(item.get("@type", "")).lower() == "jobposting":
                    return item
    return {}


def detect_remote(json_ld: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(remote_work_type_code, raw)`` from the block's own fields.

    Only an explicit Schema.org signal is used. ``TELECOMMUTE`` means the
    posting is remote; the country scope is the honest default because the
    block does not say which region the job is open to.
    """
    raw = json_ld.get("jobLocationType")
    text = (
        clean_text(raw)
        if not isinstance(raw, (list, tuple))
        else " ".join(clean_text(item) for item in raw)
    )
    if "TELECOMMUTE" in text.upper():
        return "remote_country", text or None
    if json_ld.get("applicantLocationRequirements"):
        return "remote_country", text or "applicantLocationRequirements"
    return None, (text or None)


def _first_location(json_ld: dict[str, Any]) -> dict[str, Any]:
    """Read ``jobLocation`` whether the block uses an object or a list."""
    location = json_ld.get("jobLocation")
    if isinstance(location, list):
        for item in location:
            if isinstance(item, dict):
                location = item
                break
        else:
            return {}
    if not isinstance(location, dict):
        return {}
    address = location.get("address")
    return address if isinstance(address, dict) else {}


def _company_fields(json_ld: dict[str, Any]) -> tuple[str, str | None]:
    """Return ``(company_name, logo_url)`` from ``hiringOrganization``."""
    organization = json_ld.get("hiringOrganization")
    if isinstance(organization, str):
        return clean_text(organization) or "Confidential Employer", None
    if not isinstance(organization, dict):
        return "Confidential Employer", None
    name = clean_text(organization.get("name")) or "Confidential Employer"
    logo = organization.get("logo")
    if isinstance(logo, dict):
        logo = logo.get("url") or logo.get("contentUrl")
    logo_text = clean_text(logo)
    return name, (logo_text if logo_text.lower().startswith(("http://", "https://")) else None)


def _structured_summary(json_ld: dict[str, Any], address: dict[str, Any]) -> str:
    """A labelled, non-invented summary for an ad with no body text."""
    lines = ["Oferta de empleo publicada en Chiletrabajos."]
    for label, value in (
        ("Cargo", json_ld.get("title")),
        ("Industria", json_ld.get("industry")),
        ("Comuna", address.get("addressLocality")),
        ("Región", map_region_code(address.get("addressRegion"))),
    ):
        text = clean_text(value)
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


class ChiletrabajosClParser:
    """Turns one Chiletrabajos ad page into a validated ``CleanedJob``."""

    def parse_job(self, raw: RawChiletrabajosJob) -> CleanedJob:
        """Parse one ad page into a ``CleanedJob``."""
        if not raw.html_content:
            raise ChiletrabajosClParseError(
                f"no HTML for Chiletrabajos posting {raw.job_id} ({raw.url})"
            )

        soup = BeautifulSoup(raw.html_content, "html.parser")
        json_ld = extract_job_posting(soup)

        title = clean_text(json_ld.get("title"))
        if not title:
            heading = soup.find("h1") or soup.find("h2")
            title = clean_text(heading.get_text(" ", strip=True) if heading else "")
        if not title and soup.title:
            title = clean_text((soup.title.string or "").split("|")[0])
        if not title:
            raise ChiletrabajosClParseError(
                f"no title in Chiletrabajos posting {raw.job_id} ({raw.url})"
            )

        company, logo_url = _company_fields(json_ld)
        address = _first_location(json_ld)
        location, location_parts = build_location(address)

        remote_code, remote_raw = detect_remote(json_ld)
        employment_raw = json_ld.get("employmentType")
        employment_code = map_employment_type(employment_raw)

        posting_date = parse_date(json_ld.get("datePosted"))
        closing_date = parse_date(json_ld.get("validThrough"))
        if posting_date and closing_date and closing_date < posting_date:
            closing_date = None

        salary_min, salary_max, currency, pay_period, salary_disclosed = parse_salary(json_ld)

        body = normalize_description(json_ld.get("description"))
        if body:
            description_source = "json_ld.description"
        else:
            body = _structured_summary(json_ld, address)
            description_source = "structured_summary"

        words = len(body.split())
        score = 0.4
        score += 0.2 if words >= 60 else (0.1 if words >= 20 else 0.0)
        score += 0.1 if company != "Confidential Employer" else 0.0
        score += 0.1 if location != "CL" else 0.0
        score += 0.1 if salary_disclosed else 0.0
        score += 0.05 if posting_date else 0.0
        if description_source == "structured_summary":
            score = min(score, 0.6)

        job_id = extract_identifier(json_ld, raw.job_id)
        raw_payload = {
            "url": raw.url,
            "sitemap_position": raw.sitemap_position,
            "sitemap_total": raw.sitemap_total,
            "sitemap_lastmod": raw.lastmod,
            "description_source": description_source,
            "description_chars": len(body),
            "employment_type_raw": employment_raw,
            "remote_raw": remote_raw,
            "industry": json_ld.get("industry"),
            "address": address,
            "location_parts": location_parts,
            "postal_code": address.get("postalCode"),
            "logo_raw": json_ld.get("hiringOrganization"),
            "json_ld": json_ld,
        }

        return CleanedJob(
            source_job_id=job_id,
            job_title=title,
            company_name=company,
            company_logo_url=logo_url,
            skills=[],
            location_cleaned=location,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=body or None,
            word_count=words,
            apply_url=raw.url,
            original_url=raw.url,
            posting_date=posting_date,
            closing_date=closing_date,
            data_quality_score=round(min(score, 0.95), 2),
            raw_payload=raw_payload,
            currency_iso_code=currency,
            pay_period=pay_period,
            employment_type_code=employment_code,
            remote_work_type_code=remote_code,
        )

    def parse_jobs(self, raw_jobs: list[RawChiletrabajosJob]) -> list[CleanedJob]:
        """Parse a batch, skipping and logging individual failures."""
        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.parse_job(raw))
            except ChiletrabajosClParseError as exc:
                logger.warning("Skipping Chiletrabajos posting {}: {}", raw.job_id, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Unexpected parse error for Chiletrabajos posting {}: {}",
                    raw.job_id,
                    exc,
                )
        return cleaned
