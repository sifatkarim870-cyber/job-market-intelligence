"""Parser for Emploi.cm (emploi.cm) vacancy detail pages.

The detail page carries a Schema.org ``JobPosting`` JSON-LD block with the
title, dates, employment type, employer, address and an HTML description. A
second ``WebSite`` block is present but not a posting, so only blocks that
mention ``JobPosting`` are read.

The same defect Emploi.ci and Emploi.cd exhibit appears here too: some
``description`` values embed unescaped double quotes from inline HTML
(``<p align="left">``). The block is repaired by dropping just the description
field and parsing the rest; the description itself is then read from the
page's ``div.job-description``, which is the same text without the broken
escaping.

Two measured properties of *this* board shape the output:

  * ``jobLocation.address.addressCountry`` is the French label ``Cameroun`` (the
    DRC sister site writes a boilerplate country instead), so it is normalised
    to the seeded ref.countries name and otherwise trusted.
  * ``jobLocation.address.addressRegion`` is not a region at all -- it is the
    list of cities the ad is open to (``"Douala - Yaoundé"``). Appending it to
    the locality produced strings like ``"Douala, Douala - Yaoundé, Cameroon"``,
    so the region is used for remote detection only and never stored as a place.

Everything else is best-effort and honest:

  * ``identifier.value`` is the canonical ad id; the URL-derived discovery id
    is only a fallback for a page whose JSON-LD is unreadable.
  * ``employmentType`` is often a multi-value string
    (``"CDI - CDD - Freelance"``). Mapping that to one code would be a guess,
    so an ambiguous value becomes ``None`` and the raw string is kept in
    ``raw_payload``.
  * ``baseSalary`` was absent on every sampled ad. The home-market currency
    (XAF) and monthly period state the market, not an amount.
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

from .exceptions import EmploiCmParseError
from .models import RawEmploiCmJob

HOME_COUNTRY = "Cameroon"
HOME_CURRENCY = "XAF"

#: ``"CDI - CDD"`` is two values; ``"Full-time"`` is one. Only a spaced
#: hyphen, slash or comma is a separator, never a bare hyphen inside a word.
_EMPLOYMENT_SEPARATOR_RE = re.compile(r"\s+-\s+|\s*/\s*|\s*,\s*|\s*;\s*", re.IGNORECASE)

_EMPLOYMENT_MAP: dict[str, str] = {
    "cdi": "full_time",
    "cdd": "temporary",
    "intérim": "temporary",
    "interim": "temporary",
    "temporary": "temporary",
    "freelance": "freelance",
    "stage": "internship",
    "internship": "internship",
    "temps partiel": "part_time",
    "part time": "part_time",
    "full time": "full_time",
    "permanent": "full_time",
    "contract": "contract",
    "contrat": "contract",
}

_REMOTE_TERMS = (
    "remote",
    "télétravail",
    "teletravail",
    "à distance",
    "a distance",
    #: The Cameroon board writes "En Ligne" (online) as the locality for
    #: work-from-anywhere ads, with addressRegion "International".
    "en ligne",
)
_GLOBAL_TERMS = ("international", "worldwide", "global", "monde entier")

_SKILL_WORDS = frozenset(
    {
        "python",
        "java",
        "sql",
        "excel",
        "sap",
        "javascript",
        "comptabilité",
        "comptabilite",
        "gestion",
        "marketing",
        "anglais",
        "management",
        "vente",
        "logistique",
        "finance",
        "transit",
        "douane",
        "rh",
        "ressources humaines",
    }
)


def clean_text(value: str | None) -> str:
    """Unescape entities and collapse whitespace."""
    if not value:
        return ""
    return " ".join(html.unescape(str(value)).split()).strip()


def map_employment_type(value: Any) -> str | None:
    """Map a JSON-LD employmentType to a ref.employment_types code.

    A single recognised value is mapped. Two or more *different* values -- the
    common ``"CDI - CDD - Freelance"`` shape -- return ``None`` rather than
    picking one, because the ad is explicitly offering all of them. Several
    values that all map to the same code are not ambiguous.
    """
    if value is None:
        return None
    if isinstance(value, list):
        tokens = [clean_text(str(item)) for item in value if clean_text(str(item))]
    else:
        text = clean_text(str(value))
        if not text:
            return None
        tokens = [token.strip() for token in _EMPLOYMENT_SEPARATOR_RE.split(text) if token.strip()]

    if not tokens:
        return None
    codes = {_EMPLOYMENT_MAP[token.lower()] for token in tokens if token.lower() in _EMPLOYMENT_MAP}
    if len(codes) == 1:
        return next(iter(codes))
    return None


def detect_remote(*texts: str | None) -> str:
    """Return a ref.remote_work_types code from title/locality/region text."""
    haystack = " ".join(text.lower() for text in texts if text)
    if not any(term in haystack for term in _REMOTE_TERMS):
        return "on_site"
    if any(term in haystack for term in _GLOBAL_TERMS):
        return "remote_global"
    return "remote_country"


def normalize_country(value: str | None) -> str:
    """Map the board's country label onto the seeded ref.countries name."""
    text = clean_text(value)
    lowered = text.lower()
    if "cameroun" in lowered or "cameroon" in lowered or lowered in {"cm", "cmr"}:
        return HOME_COUNTRY
    return text


def _looks_like_city_list(locality: str, region: str) -> bool:
    """True when ``addressLocality`` is really the board's multi-city list.

    Measured shape: the ad is open to five cities and the board writes them
    space-separated into ``addressLocality`` (``"Douala Yaoundé Bafoussam
    Garoua Maroua"``) while ``addressRegion`` carries the same set dash-
    separated. That is a filter list, not a place. A real locality has at most
    a token or two, so three or more tokens that also appear in the region is
    the list. Requiring two matches keeps a genuine long place name (whose
    region is usually empty or the same single city) out of the rule.
    """
    tokens = [token for token in re.split(r"\s+", locality) if token]
    if len(tokens) < 3:
        return False
    region_parts = {
        part.strip().casefold() for part in re.split(r"\s+-\s+", region) if part.strip()
    }
    if not region_parts:
        return False
    overlap = sum(1 for token in tokens if token.casefold() in region_parts)
    return overlap >= 2


def build_location(address: dict[str, Any], remote_code: str) -> str:
    """Compose a readable location from the locality, never the city list.

    ``addressRegion`` is dropped on purpose: on this board it is the list of
    cities the ad is open to, not a region, so keeping it would repeat the
    locality and produce things like ``"Douala, Douala - Yaoundé"``.
    A locality that is itself such a list, or that is just the country label
    (``"Cameroun"``), is dropped too: naming one of five cities would be a
    guess. The full values stay in ``raw_payload`` and are still used for
    remote detection in ``detect_remote``.
    """
    locality = clean_text(address.get("addressLocality"))
    region = clean_text(address.get("addressRegion"))
    country = normalize_country(address.get("addressCountry")) or HOME_COUNTRY

    if normalize_country(locality) == country:
        locality = ""
    if _looks_like_city_list(locality, region):
        locality = ""

    if remote_code.startswith("remote") and (
        not locality
        or "remote" in locality.lower()
        or locality.startswith("/")
        or locality.lower() in {"en ligne", "online"}
    ):
        locality = "Remote"

    parts: list[str] = []
    for part in (locality, country):
        if part and part not in parts:
            parts.append(part)
    return ", ".join(parts) if parts else HOME_COUNTRY


def parse_date(value: Any) -> datetime | None:  # noqa: C901 - one branch per date shape
    """Parse an ISO or day-first French date into a ``datetime``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None

    iso = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if iso:
        try:
            return datetime.strptime(iso.group(1), "%Y-%m-%d")
        except ValueError:
            return None

    french = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if french:
        day, month, year = (int(part) for part in french.groups())
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def extract_identifier(json_ld: dict[str, Any], fallback: str) -> str:
    """The canonical ad id from ``identifier.value``, else the discovery id."""
    identifier = json_ld.get("identifier")
    if isinstance(identifier, dict):
        value = identifier.get("value")
        if value not in (None, ""):
            return str(value).strip()
    elif isinstance(identifier, str) and identifier.strip():
        return identifier.strip()
    return fallback


def _repair_description_field(content: str) -> str:
    """Drop only the ``description`` field from a JSON-LD block.

    Two patterns are tried because the next key is usually ``identifier`` but
    is not guaranteed to be. The non-greedy match stops at the first ``",``
    that begins the following key, which is exactly where the unescaped inline
    HTML quotes end.
    """
    repaired = re.sub(
        r'"description"\s*:\s*".*?"\s*,\s*"identifier"',
        '"identifier"',
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


def extract_json_ld(soup: BeautifulSoup) -> dict[str, Any]:  # noqa: C901 - one branch per block shape
    """Find and parse the Schema.org ``JobPosting`` block, repairing bad quotes."""
    for script in soup.find_all("script", type="application/ld+json"):
        content = (script.string or script.text or "").strip()
        if "JobPosting" not in content and "jobposting" not in content:
            continue

        for candidate in (content, _repair_description_field(content)):
            try:
                data = json.loads(candidate, strict=False)
            except (json.JSONDecodeError, ValueError):
                continue

            if isinstance(data, list):
                for item in data:
                    if (
                        isinstance(item, dict)
                        and str(item.get("@type", "")).lower() == "jobposting"
                    ):
                        return item
            if isinstance(data, dict):
                if str(data.get("@type", "")).lower() == "jobposting":
                    return data
                graph = data.get("@graph")
                if isinstance(graph, list):
                    for item in graph:
                        if (
                            isinstance(item, dict)
                            and str(item.get("@type", "")).lower() == "jobposting"
                        ):
                            return item
    return {}


def extract_description(soup: BeautifulSoup, json_ld: dict[str, Any]) -> tuple[str | None, str]:
    """Return ``(description, source)`` from the cleanest container available."""
    container = soup.find("div", class_="job-description")
    if container:
        text = container.get_text("\n", strip=True)
        source = "div.job-description"
    elif json_ld.get("description"):
        text = BeautifulSoup(str(json_ld["description"]), "html.parser").get_text("\n", strip=True)
        source = "json_ld.description"
    else:
        fallback = soup.find(class_=re.compile(r"job-detail|description|job-content", re.I))
        text = fallback.get_text("\n", strip=True) if fallback else ""
        source = "fallback_container" if fallback else "none"

    text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    return (text or None), source


class EmploiCmParser:
    """Extracts structured ``CleanedJob`` records from Emploi.cm pages."""

    def parse_job(self, raw: RawEmploiCmJob) -> CleanedJob:  # noqa: C901 - field-by-field contract
        """Parse one Emploi.cm detail page into a ``CleanedJob``."""
        soup = BeautifulSoup(raw.html_content, "html.parser")
        json_ld = extract_json_ld(soup)

        title = clean_text(json_ld.get("title"))
        if not title:
            heading = soup.find("h1") or soup.find("h2")
            title = clean_text(heading.get_text() if heading else "")
        if not title and soup.title:
            title = clean_text((soup.title.string or "").split("|")[0])
        if not title:
            raise EmploiCmParseError(f"no title in Emploi.cm posting {raw.job_id} ({raw.url})")

        org = json_ld.get("hiringOrganization")
        company = ""
        if isinstance(org, dict):
            company = clean_text(org.get("name"))
        elif isinstance(org, str):
            company = clean_text(org)
        if not company:
            heading = soup.find("h3")
            company = clean_text(heading.get_text() if heading else "")
        if not company:
            company_elem = soup.find(class_=re.compile(r"company-name|card-block-company", re.I))
            if company_elem:
                company = re.split(
                    r"\bSecteur\b",
                    clean_text(company_elem.get_text(" ", strip=True)),
                    maxsplit=1,
                )[0].strip()
        if not company or company.lower() in {"confidentiel", "confidential", "anonyme"}:
            company = "Confidential Employer"

        address = {}
        job_location = json_ld.get("jobLocation")
        if isinstance(job_location, dict) and isinstance(job_location.get("address"), dict):
            address = job_location["address"]

        remote_code = detect_remote(
            title,
            clean_text(address.get("addressLocality")),
            clean_text(address.get("addressRegion")),
        )
        location = build_location(address, remote_code)

        posting_date = parse_date(json_ld.get("datePosted"))
        closing_date = parse_date(json_ld.get("validThrough"))
        if not posting_date:
            match = re.search(r"Publi[ée]e?\s+le\s+(\d{1,2}[./]\d{1,2}[./]\d{4})", raw.html_content)
            if match:
                posting_date = parse_date(match.group(1))
        if posting_date and closing_date and closing_date < posting_date:
            closing_date = None

        employment_raw = json_ld.get("employmentType")
        employment_code = map_employment_type(employment_raw)

        salary_disclosed = False
        salary_min: float | None = None
        salary_max: float | None = None
        currency_iso_code = HOME_CURRENCY
        pay_period = "monthly"
        base_salary = json_ld.get("baseSalary")
        if isinstance(base_salary, dict):
            currency = base_salary.get("currency")
            if currency:
                currency_iso_code = str(currency).strip().upper()
            value = base_salary.get("value")
            if isinstance(value, dict):
                unit = str(value.get("unitText") or "").upper()
                if "YEAR" in unit or "AN" in unit:
                    pay_period = "yearly"
                elif "HOUR" in unit or "HEURE" in unit:
                    pay_period = "hourly"
                min_value = value.get("minValue")
                max_value = value.get("maxValue") or min_value
                for bound in (min_value, max_value):
                    if bound is None:
                        continue
                    try:
                        parsed = float(bound)
                    except (TypeError, ValueError):
                        continue
                    if bound is min_value:
                        salary_min = parsed
                    else:
                        salary_max = parsed
                    salary_disclosed = True

        description, description_source = extract_description(soup, json_ld)
        words = len(description.split()) if description else 0

        lowered = (description or "").lower()
        skills: list[str] = []
        for word in re.findall(r"[A-Za-zÀ-ÿ#+]{2,}", description or ""):
            if word.lower() in _SKILL_WORDS:
                normalized = word.capitalize()
                if normalized not in skills:
                    skills.append(normalized)

        raw_payload = {
            "url": raw.url,
            "discovered_job_id": raw.job_id,
            "title": title,
            "company": company,
            "location": location,
            "employment_type_raw": employment_raw,
            "remote_hint": remote_code,
            "address": address,
            "description_source": description_source,
            "description_has_remote_mention": any(term in lowered for term in _REMOTE_TERMS),
            "json_ld": json_ld,
        }

        return CleanedJob(
            source_job_id=extract_identifier(json_ld, raw.job_id),
            job_title=title,
            company_name=company,
            company_logo_url=None,
            skills=skills,
            location_cleaned=location,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=description,
            word_count=words,
            apply_url=raw.url,
            original_url=raw.url,
            posting_date=posting_date,
            closing_date=closing_date,
            data_quality_score=0.95 if words > 50 else 0.7,
            raw_payload=raw_payload,
            currency_iso_code=currency_iso_code,
            pay_period=pay_period,
            employment_type_code=employment_code,
            remote_work_type_code=remote_code,
        )

    def parse_jobs(self, raw_jobs: list[RawEmploiCmJob]) -> list[CleanedJob]:
        """Parse a batch, skipping and logging individual failures."""
        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.parse_job(raw))
            except EmploiCmParseError as exc:
                logger.warning("Skipping Emploi.cm posting {}: {}", raw.job_id, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Unexpected parse error for Emploi.cm posting {}: {}",
                    raw.job_id,
                    exc,
                )
        return cleaned
