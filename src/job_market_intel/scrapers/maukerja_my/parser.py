"""Parser for MauKerja (maukerja.my) ad pages.

Every ad page carries a Schema.org ``JobPosting`` JSON-LD block (the page's
other block is a ``BreadcrumbList``). The block was measured on live pages on
2026-11-20 and has these shapes:

* ``identifier`` is a ``PropertyValue``: ``{"@type": "PropertyValue",
  "name": "<company>", "value": "<10-char id>"}``. ``value`` matches the id
  embedded in the URL (``/job/<id>-<slug>``).
* ``baseSalary`` is a ``MonetaryAmount`` whose ``value`` is a
  ``QuantitativeValue`` with ``value``/``minValue``/``maxValue`` (all ints)
  and ``unitText: "MONTH"``. An all-zero value means "salary not published",
  not "zero ringgit". ``salaryCurrency`` is ``MYR``.
* ``datePosted``/``validThrough`` are ISO-8601 with a literal ``Z``. Older ads
  carry a far-future ``validThrough`` (e.g. ``2119-08-29``) as a "never
  expires" sentinel; it is stored as the source published it rather than
  reinterpreted.
* ``hiringOrganization`` is ``{name, logo, sameAs}``; ``logo`` is sometimes a
  placeholder under ``files.ajobthing.com``.
* ``jobLocation.address`` is ``{"addressLocality": "<town>",
  "addressRegion": "<state>", "addressCountry": "MY"}``. ``addressRegion`` is
  usually a state name but is sometimes the federal-territory form
  ``WP Kuala Lumpur`` (normalised to ``Kuala Lumpur``) and occasionally a bare
  postal code (rejected). ``addressCountry`` is ``MY`` on essentially every ad
  with the occasional ``SG``.
* ``employmentType`` is a **list** of Schema.org codes (``["FULL_TIME"]``).
* ``skills`` and ``jobBenefits`` are lists of strings; ``occupationalCategory``
  is free text.

``jobLocationType`` was absent on every ad sampled, so ``remote_work_type_code``
is set only when the block itself says ``TELECOMMUTE``; nothing is inferred
from prose.
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

from .exceptions import MaukerjaMyParseError
from .models import RawMaukerjaMyJob

#: Schema.org employment type -> ``ref.employment_types.code``. Codes with no
#: equivalent in this schema (``VOLUNTEER``, ``PER_DIEM``, ``OTHER``) map to
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

#: ``addressCountry`` values the board writes -> ISO 3166-1 alpha-2.
_COUNTRY_ALIASES = {
    "MY": "MY",
    "MALAYSIA": "MY",
    "SG": "SG",
    "SINGAPORE": "SG",
}

#: The federal-territory spelling ("WP Kuala Lumpur") carries a "Wilayah
#: Persekutuan" prefix the seeded region names do not.
_WP_PREFIX = re.compile(r"^WP\s+", re.IGNORECASE)

_DEFAULT_COUNTRY = "MY"


def clean_text(value: Any) -> str:
    """Unescape entities and collapse whitespace."""
    if value is None:
        return ""
    return " ".join(html.unescape(str(value)).split()).strip()


def parse_salary_amount(value: Any) -> float | None:
    """Parse a ringgit amount into a positive float.

    Amounts are normally plain integers (``2300`` or ``"2300"``), but thousands
    separators are handled too. ``0`` means "not published", not "zero ringgit".
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
        for key in ("value", "Value", "amount"):
            if key in value:
                return parse_salary_amount(value[key])
        return None
    return parse_salary_amount(value)


def parse_salary(json_ld: dict[str, Any]) -> tuple[float | None, float | None, str, str, bool]:
    """Return ``(min, max, currency, pay_period, disclosed)`` for one ad.

    A single published amount is stored as ``salary_min`` only; the schema does
    not say it is a range, and inventing a maximum would be a claim the ad did
    not make.
    """
    currency = clean_text(json_ld.get("salaryCurrency")) or "MYR"
    pay_period = "monthly"
    base_salary = json_ld.get("baseSalary")
    if not isinstance(base_salary, dict):
        return None, None, currency, pay_period, False

    if base_salary.get("currency"):
        currency = str(base_salary["currency"]).strip().upper()

    value = base_salary.get("value")
    if not isinstance(value, dict):
        amount = _salary_number(value)
        if amount is None:
            return None, None, currency, pay_period, False
        return amount, None, currency, pay_period, True

    unit = str(value.get("unitText") or "").strip().upper()
    for needle, period in _PAY_PERIODS.items():
        if needle in unit:
            pay_period = period
            break

    minimum = _salary_number(value.get("minValue"))
    maximum = _salary_number(value.get("maxValue"))
    if minimum is None:
        minimum = _salary_number(value.get("value"))
    if minimum is None and maximum is None:
        return None, None, currency, pay_period, False
    if minimum is not None and maximum is not None and maximum < minimum:
        minimum, maximum = maximum, minimum
    return minimum, maximum, currency, pay_period, True


def map_employment_type(raw: Any) -> str | None:
    """Map a Schema.org ``employmentType`` onto one code, or ``None``.

    The board publishes a **list**; when it holds two different codes (e.g.
    both ``FULL_TIME`` and ``PART_TIME``) that is two different answers, so it
    is stored as ``None`` instead of picking one. The raw value is kept in
    ``raw_payload``.
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


def map_region(raw: Any) -> str | None:
    """Normalise ``addressRegion`` into a place name, or ``None``.

    ``WP Kuala Lumpur`` collapses to ``Kuala Lumpur`` so it matches the seeded
    federal-territory region, and a bare postal code (``81750``) is dropped so
    it cannot masquerade as a state. Any other value is returned as written:
    the resolver only matches seeded region names, so an unrecognised string
    falls through to the country rather than becoming a bogus region.
    """
    text = _region_text(raw)
    if not text:
        return None
    text = _WP_PREFIX.sub("", text).strip()
    if not text or text.isdigit():
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
    """Compose ``"<locality>; <region>; <country>"`` and return the raw parts.

    The city is the board's ``addressLocality``; keeping it means a seeded town
    resolves at city level and an unseeded one still resolves at region level.
    The country segment is the ISO-2 code so the resolver cannot confuse it
    with a place name.
    """
    city = _address_part(address.get("addressLocality"))
    region = map_region(address.get("addressRegion"))
    country_raw = _address_part(address.get("addressCountry"))
    country = _COUNTRY_ALIASES.get(country_raw.upper(), _DEFAULT_COUNTRY)

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
    return ("; ".join(parts) if parts else _DEFAULT_COUNTRY), {
        "city": city,
        "region": region or "",
        "country_raw": country_raw,
        "country_iso2": country,
    }


def parse_date(value: Any) -> datetime | None:
    """Parse the ISO-8601 (``Z``) date shapes the board writes into naive UTC."""
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
    """Use the publisher's ``identifier.value`` when present, else the URL id."""
    identifier = json_ld.get("identifier")
    value: Any = None
    if isinstance(identifier, dict):
        value = identifier.get("value")
    elif isinstance(identifier, (str, int)):
        value = identifier
    text = clean_text(value)
    return text or fallback


def _string_list(raw: Any) -> list[str]:
    """Read a JSON-LD list of strings, or a single string, into a clean list."""
    if raw is None:
        return []
    values = raw if isinstance(raw, (list, tuple)) else [raw]
    out: list[str] = []
    for item in values:
        text = clean_text(item)
        if text and text not in out:
            out.append(text)
    return out


def _repair_description_field(content: str) -> str:
    """Drop only the ``description`` field from a JSON-LD block.

    The board escapes its descriptions correctly on every page measured, but
    the repair is cheap and keeps one malformed ad from losing the other fields.
    Two patterns are tried because the key after ``description`` is not
    guaranteed.
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
    """Return ``(company_name, logo_url)`` from ``hiringOrganization``.

    Falls back to the ``identifier.name`` the board also writes (it duplicates
    the employer) when ``hiringOrganization`` is missing or unnamed.
    """
    organization = json_ld.get("hiringOrganization")
    name = ""
    logo: Any = None
    if isinstance(organization, str):
        name = clean_text(organization)
    elif isinstance(organization, dict):
        name = clean_text(organization.get("name"))
        logo = organization.get("logo")
    if not name:
        identifier = json_ld.get("identifier")
        if isinstance(identifier, dict):
            name = clean_text(identifier.get("name"))
    if isinstance(logo, dict):
        logo = logo.get("url") or logo.get("contentUrl")
    logo_text = clean_text(logo)
    return (
        name or "Confidential Employer",
        logo_text if logo_text.lower().startswith(("http://", "https://")) else None,
    )


def _structured_summary(json_ld: dict[str, Any], address: dict[str, Any]) -> str:
    """A labelled, non-invented summary for an ad with no body text."""
    lines = ["Iklan kerja yang disiarkan di MauKerja."]
    for label, value in (
        ("Jawatan", json_ld.get("title")),
        ("Kategori", json_ld.get("occupationalCategory")),
        ("Bandar", address.get("addressLocality")),
        ("Negeri", map_region(address.get("addressRegion"))),
    ):
        text = clean_text(value)
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


class MaukerjaMyParser:
    """Turns one MauKerja ad page into a validated ``CleanedJob``."""

    def parse_job(self, raw: RawMaukerjaMyJob) -> CleanedJob:
        """Parse one ad page into a ``CleanedJob``."""
        if not raw.html_content:
            raise MaukerjaMyParseError(f"no HTML for MauKerja posting {raw.job_id} ({raw.url})")

        soup = BeautifulSoup(raw.html_content, "html.parser")
        json_ld = extract_job_posting(soup)

        title = clean_text(json_ld.get("title"))
        if not title:
            heading = soup.find("h1") or soup.find("h2")
            title = clean_text(heading.get_text(" ", strip=True) if heading else "")
        if not title and soup.title:
            title = clean_text((soup.title.string or "").split("|")[0])
        if not title:
            raise MaukerjaMyParseError(f"no title in MauKerja posting {raw.job_id} ({raw.url})")

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
        score += 0.1 if location != _DEFAULT_COUNTRY else 0.0
        score += 0.1 if salary_disclosed else 0.0
        score += 0.05 if posting_date else 0.0
        if description_source == "structured_summary":
            score = min(score, 0.6)

        job_id = extract_identifier(json_ld, raw.job_id)
        skills = _string_list(json_ld.get("skills"))
        benefits = _string_list(json_ld.get("jobBenefits"))
        raw_payload = {
            "url": raw.url,
            "sitemap_position": raw.sitemap_position,
            "sitemap_total": raw.sitemap_total,
            "sitemap_lastmod": raw.lastmod,
            "description_source": description_source,
            "description_chars": len(body),
            "employment_type_raw": employment_raw,
            "remote_raw": remote_raw,
            "occupational_category": json_ld.get("occupationalCategory"),
            "skills": skills,
            "job_benefits": benefits,
            "address": address,
            "location_parts": location_parts,
            "salary_currency": currency,
            "direct_apply": json_ld.get("directApply"),
            "identifier": json_ld.get("identifier"),
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

    def parse_jobs(self, raw_jobs: list[RawMaukerjaMyJob]) -> list[CleanedJob]:
        """Parse a batch, skipping and logging individual failures."""
        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.parse_job(raw))
            except MaukerjaMyParseError as exc:
                logger.warning("Skipping MauKerja posting {}: {}", raw.job_id, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Unexpected parse error for MauKerja posting {}: {}", raw.job_id, exc
                )
        return cleaned
