"""Parser for jobup.ch ad pages.

Every ad page carries a Schema.org ``JobPosting`` JSON-LD block (the page's
other block is a ``BreadcrumbList``). The block was measured on live pages on
2026-11-20 and has these shapes:

* ``title`` and ``description`` (HTML) are always present; ``datePosted`` is
  ISO-8601 with an offset.
* ``hiringOrganization`` is ``{name, logo, sameAs}``; ``logo`` is a string.
  Older/minimal ads carry only ``name``.
* ``jobLocation.address`` is ``{addressLocality, addressRegion,
  addressCountry}``. ``addressCountry`` was ``CH`` on 100% of ads sampled.
  ``addressLocality``/``addressRegion`` are often absent and inconsistent when
  present: a town can appear in the region slot, a postcode in parentheses can
  trail a town (``"Lachen SZ (8853 Lachen)"``), and some values are internal
  paths (``"EMEA > CHE > Stabio > ..."``) or prose (``"Je nach Baustelle im
  Oberwallis"``). Such values are rejected rather than stored as a bogus place.
* ``employmentType`` is **either** a list of Schema.org codes
  (``["FULL_TIME"]``) **or** a prose string (``"Permanent position"``,
  ``"Temporary"``, ``"Apprenticeship"``).
* ``baseSalary`` is a ``MonetaryAmount`` (``currency: CHF``) whose ``value`` is
  a ``QuantitativeValue`` with ``minValue``/``maxValue`` and
  ``unitText: YEAR`` when a salary is published. About a third of the sampled
  ads carried a block and roughly half of those had an empty
  ``QuantitativeValue`` -- published but with no numbers, stored as
  undisclosed rather than zero francs.
* ``identifier`` is a ``PropertyValue`` whose ``value`` is the ad UUID.
* ``applicantLocationRequirements`` is ``{"@type": "Country", "name":
  "Switzerland"}`` an eligibility statement, **not** a remote signal. Only an
  explicit ``jobLocationType: TELECOMMUTE`` sets a remote type.

Two extra coarse fields are kept in ``raw_payload`` and not mapped onto the
schema because they are not reliable: ``totalJobOpenings`` (an ad sampled on
2026-11-20 claimed 2,757 openings, a placeholder) and ``workHours`` (free
text). Nothing is inferred from prose.
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

from .exceptions import JobupChParseError
from .models import RawJobupChJob

#: Schema.org employment type -> ``ref.employment_types.code``.
_EMPLOYMENT_CODES: dict[str, str] = {
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

#: The board also publishes prose strings in ``employmentType``. "Permanent
#: position" has no equivalent code in this schema and is deliberately left
#: ``None`` rather than guessed as full-time.
_EMPLOYMENT_PROSE: dict[str, str] = {
    "temporary": "temporary",
    "apprenticeship": "apprenticeship",
    "apprenticeship position": "apprenticeship",
    "internship": "internship",
    "freelance": "freelance",
    "contract": "contract",
    "part-time": "part_time",
    "part time": "part_time",
    "full-time": "full_time",
    "full time": "full_time",
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
    "CH": "CH",
    "CHE": "CH",
    "SWITZERLAND": "CH",
    "SUISSE": "CH",
    "SCHWEIZ": "CH",
    "SVIZZERA": "CH",
    "LI": "LI",
    "LUXEMBOURG": "LU",
    "LU": "LU",
    "DE": "DE",
    "GERMANY": "DE",
    "AT": "AT",
    "AUSTRIA": "AT",
    "FR": "FR",
    "FRANCE": "FR",
}

_DEFAULT_COUNTRY = "CH"

#: The 26 cantons, with the spellings the board is most likely to write, mapped
#: onto the canonical name seeded in ``ref.regions``.
_CANTON_ALIASES: dict[str, str] = {
    "zürich": "Zürich",
    "zurich": "Zürich",
    "bern": "Bern",
    "berne": "Bern",
    "luzern": "Luzern",
    "lucerne": "Luzern",
    "uri": "Uri",
    "schwyz": "Schwyz",
    "obwalden": "Obwalden",
    "nidwalden": "Nidwalden",
    "niderwalden": "Nidwalden",
    "glarus": "Glarus",
    "glaris": "Glarus",
    "zug": "Zug",
    "fribourg": "Fribourg",
    "freiburg": "Fribourg",
    "solothurn": "Solothurn",
    "soleure": "Solothurn",
    "basel-stadt": "Basel-Stadt",
    "basel stadt": "Basel-Stadt",
    "basel-landschaft": "Basel-Landschaft",
    "basel landschaft": "Basel-Landschaft",
    "schaffhausen": "Schaffhausen",
    "schaffhouse": "Schaffhausen",
    "appenzell ausserrhoden": "Appenzell Ausserrhoden",
    "appenzell innerrhoden": "Appenzell Innerrhoden",
    "st. gallen": "St. Gallen",
    "st gallen": "St. Gallen",
    "sankt gallen": "St. Gallen",
    "graubünden": "Graubünden",
    "grisons": "Graubünden",
    "aargau": "Aargau",
    "argovie": "Aargau",
    "thurgau": "Thurgau",
    "thurgovie": "Thurgau",
    "ticino": "Ticino",
    "tessin": "Ticino",
    "vaud": "Vaud",
    "waadt": "Vaud",
    "valais": "Valais",
    "wallis": "Valais",
    "neuchâtel": "Neuchâtel",
    "neuenburg": "Neuchâtel",
    "genève": "Genève",
    "geneve": "Genève",
    "genf": "Genève",
    "geneva": "Genève",
    "jura": "Jura",
}

#: Two-letter canton codes that the board appends to a town ("Wetzikon ZH").
_CANTON_CODES = {
    "ZH",
    "BE",
    "LU",
    "UR",
    "SZ",
    "OW",
    "NW",
    "GL",
    "ZG",
    "FR",
    "SO",
    "BS",
    "BL",
    "SH",
    "AR",
    "AI",
    "SG",
    "GR",
    "AG",
    "TG",
    "TI",
    "VD",
    "VS",
    "NE",
    "GE",
    "JU",
}
_TRAILING_CANTON_CODE = re.compile(r"\s+([A-Z]{2})$")
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")
_STADT_PREFIX = re.compile(r"^stadt\s+", re.IGNORECASE)


def clean_text(value: Any) -> str:
    """Unescape entities and collapse whitespace."""
    if value is None:
        return ""
    return " ".join(html.unescape(str(value)).split()).strip()


def parse_salary_amount(value: Any) -> float | None:
    """Parse a salary amount into a positive float.

    Amounts are plain numbers or numeric strings; thousands separators are
    handled. ``0`` means "not published", not "zero francs".
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
        for key in ("value", "Value", "amount", "minValue", "maxValue"):
            if key in value:
                return parse_salary_amount(value[key])
        return None
    return parse_salary_amount(value)


def parse_salary(json_ld: dict[str, Any]) -> tuple[float | None, float | None, str, str, bool]:
    """Return ``(min, max, currency, pay_period, disclosed)`` for one ad.

    A single published amount is stored as ``salary_min`` only; inventing a
    maximum would be a claim the ad did not make.
    """
    currency = clean_text(json_ld.get("salaryCurrency")) or "CHF"
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
    """Map an ``employmentType`` (list of codes or prose) onto one code.

    A list holding two different codes is two different answers and is stored
    as ``None`` rather than picking one. A prose value with no equivalent code
    (``"Permanent position"``) is also ``None``. The raw value stays in
    ``raw_payload``.
    """
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        values = [str(item) for item in raw]
    else:
        values = [str(raw)]

    codes: list[str] = []
    for value in values:
        text = clean_text(value)
        if not text:
            continue
        code = _EMPLOYMENT_CODES.get(text.upper())
        if code is None:
            code = _EMPLOYMENT_PROSE.get(text.lower())
        if code and code not in codes:
            codes.append(code)
    return codes[0] if len(codes) == 1 else None


def _clean_locality(raw: Any) -> str:
    """Normalise ``addressLocality`` into a place name (or ``""``).

    Strips a trailing parenthetical/postcode, a ``"<town> - <street>"`` tail and
    a leading ``Stadt``, and drops internal paths and prose that are not place
    names. A trailing two-letter canton code (``"Wetzikon ZH"``) is removed so
    the town matches the seeded city name exactly.

    The parentheticals are cut at the first ``(`` rather than stripped with a
    regex because the board nests them: ``"Haag (Rheintal) (9469 Buchs (SG))"``
    is a real value, and a single non-nesting pass leaves ``"Haag )"`` behind.
    """
    text = _address_part(raw)
    if not text:
        return ""
    head = text.split("(", 1)[0].strip()
    text = head if head else _PARENTHETICAL.sub("", text).strip()
    # The board also writes "<town> - <street>" ("Ilanz - Via Crappa Grossa 24").
    text = re.split(r"\s+[-\u2013]\s+", text)[0].strip()
    lowered = text.lower()
    if not text or ">" in text or "baustelle" in lowered or lowered.startswith("emea"):
        return ""
    text = _STADT_PREFIX.sub("", text).strip()
    match = _TRAILING_CANTON_CODE.search(text)
    if match and match.group(1) in _CANTON_CODES:
        text = text[: match.start()].strip()
    return text


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
    """Normalise ``addressRegion`` into a seeded canton name, or ``None``.

    Recognised canton spellings (German/French/English, plus the board's
    ``"Niderwalden"`` typo) are mapped onto the canonical seeded name. Anything
    else is returned as written only if it looks like a place: the resolver
    matches seeded region names exactly, so an unrecognised town in the region
    slot simply falls through to the country segment rather than becoming a
    bogus region.
    """
    text = _region_text(raw)
    if not text:
        return None
    text = _PARENTHETICAL.sub("", text).strip()
    lowered = text.lower()
    if not text or ">" in text or "baustelle" in lowered or lowered.startswith("emea"):
        return None
    return _CANTON_ALIASES.get(lowered, text)


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

    The board often leaves ``addressLocality`` empty and puts the town in
    ``addressRegion`` (measured: ``"Le Mont-sur-Lausanne (VD)"``, ``"Bienne"``,
    ``"Crissier"``, ``"Region Seeland"``). When the region slot is not one of
    the 26 cantons it is therefore reused as the locality, so a seeded town can
    match a city; a genuine canton name stays in the region slot. An unseeded
    town still ends up country-level, which is the honest answer.
    """
    city = _clean_locality(address.get("addressLocality"))
    region = map_region(address.get("addressRegion"))
    if not city and region and region not in _CANTON_ALIASES.values():
        city = region
        region = None
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
    """Parse the ISO-8601 date shapes the board writes into naive UTC."""
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
    the repair is cheap and keeps one malformed ad from losing the other
    fields.
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
    """Return ``(remote_work_type_code, raw)`` from an explicit remote signal.

    Only ``jobLocationType: TELECOMMUTE`` is used. ``applicantLocationRequirements``
    is an eligibility statement ("Country: Switzerland"), not a remote signal,
    so it never sets a remote type.
    """
    raw = json_ld.get("jobLocationType")
    text = (
        clean_text(raw)
        if not isinstance(raw, (list, tuple))
        else " ".join(clean_text(item) for item in raw)
    )
    if "TELECOMMUTE" in text.upper():
        return "remote_country", text or None
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
    name = ""
    logo: Any = None
    if isinstance(organization, str):
        name = clean_text(organization)
    elif isinstance(organization, dict):
        name = clean_text(organization.get("name"))
        logo = organization.get("logo")
    if isinstance(logo, dict):
        logo = logo.get("url") or logo.get("contentUrl")
    logo_text = clean_text(logo)
    return (
        name or "Confidential Employer",
        logo_text if logo_text.lower().startswith(("http://", "https://")) else None,
    )


def _structured_summary(json_ld: dict[str, Any], address: dict[str, Any]) -> str:
    """A labelled, non-invented summary for an ad with no body text."""
    lines = ["Stellenangebot auf jobup.ch."]
    for label, value in (
        ("Titel", json_ld.get("title")),
        ("Branche", json_ld.get("industry")),
        ("Kategorie", json_ld.get("occupationalCategory")),
        ("Ort", _clean_locality(address.get("addressLocality"))),
        ("Kanton", map_region(address.get("addressRegion"))),
    ):
        text = clean_text(value)
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


class JobupChParser:
    """Turns one jobup.ch ad page into a validated ``CleanedJob``."""

    def parse_job(self, raw: RawJobupChJob) -> CleanedJob:
        """Parse one ad page into a ``CleanedJob``."""
        if not raw.html_content:
            raise JobupChParseError(f"no HTML for jobup.ch posting {raw.job_id} ({raw.url})")

        soup = BeautifulSoup(raw.html_content, "html.parser")
        json_ld = extract_job_posting(soup)

        title = clean_text(json_ld.get("title"))
        if not title:
            heading = soup.find("h1") or soup.find("h2")
            title = clean_text(heading.get_text(" ", strip=True) if heading else "")
        if not title and soup.title:
            title = clean_text((soup.title.string or "").split(" - Job offer")[0])
        if not title:
            raise JobupChParseError(f"no title in jobup.ch posting {raw.job_id} ({raw.url})")

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
            "employment_unit": json_ld.get("employmentUnit"),
            "work_hours": json_ld.get("workHours"),
            "remote_raw": remote_raw,
            "applicant_location_requirements": json_ld.get("applicantLocationRequirements"),
            "industry": json_ld.get("industry"),
            "occupational_category": json_ld.get("occupationalCategory"),
            "skills": skills,
            "job_benefits": benefits,
            "address": address,
            "location_parts": location_parts,
            "salary_currency": currency,
            "job_start_date": json_ld.get("jobStartDate"),
            "total_job_openings": json_ld.get("totalJobOpenings"),
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

    def parse_jobs(self, raw_jobs: list[RawJobupChJob]) -> list[CleanedJob]:
        """Parse a batch, skipping and logging individual failures."""
        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.parse_job(raw))
            except JobupChParseError as exc:
                logger.warning("Skipping jobup.ch posting {}: {}", raw.job_id, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Unexpected parse error for jobup.ch posting {}: {}", raw.job_id, exc
                )
        return cleaned
