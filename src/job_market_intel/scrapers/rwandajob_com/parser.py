"""Parser for Rwandajob.com vacancy detail pages.

The detail page carries a Schema.org ``JobPosting`` JSON-LD block with the
title, dates, employment type, employer, address and an HTML description. A
second ``WebSite`` block is present but not a posting, so only blocks that
mention ``JobPosting`` are read.

The same defect the Rwanda host shares with its AfricaWork siblings appears here
too: some ``description`` values embed unescaped double quotes from inline HTML
(``<p align="left">``). The block is repaired by dropping just the description
field and parsing the rest; the description itself is then read from the page's
``div.job-description``, which is the same text without the broken escaping.

Measured properties of *this* board shape the output:

  * ``jobLocation.address.addressCountry`` is the clean label ``Rwanda`` and is
    trusted (normalised to the seeded ref.countries name).
  * ``jobLocation.address.addressRegion`` is not a region at all -- it is the
    ``-``-joined list of provinces the ad is open to
    (``"Eastern Province - Kigali Province - ... - International"``). Appending
    it to the locality produced strings like
    ``"Kigali, Kigali Province - International, Rwanda"``, so the region is used
    for remote detection only and never stored as a place.
  * ``datePosted`` tracks the ad (page-5 ads read ``2026-09-29`` while page-1
    ads read ``2026-11-20``, matching the visible ``Published on`` line), so it
    is stored as the posting date. ``validThrough`` is the real deadline.

Everything else is best-effort and honest:

  * ``identifier.value`` is the canonical ad id; the URL-derived discovery id
    is only a fallback for a page whose JSON-LD is unreadable.
  * ``employmentType`` is often a multi-value string
    (``"Permanent contract - Fixed-term contract - Freelance"``). Mapping that to
    one code would be a guess, so an ambiguous value becomes ``None`` and the raw
    string is kept in ``raw_payload``.
  * ``baseSalary`` was absent on every sampled ad. The home-market currency
    (RWF) and monthly period state the market, not an amount.
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

from .exceptions import RwandaJobParseError
from .models import RawRwandaJob

HOME_COUNTRY = "Rwanda"
HOME_CURRENCY = "RWF"

#: ``"Permanent contract - Fixed-term contract"`` is two values;
#: ``"Fixed-term contract"`` is one. Only a spaced hyphen, slash, comma or
#: semicolon is a separator, never a bare hyphen inside a word.
_EMPLOYMENT_SEPARATOR_RE = re.compile(r"\s+-\s+|\s*/\s*|\s*,\s*|\s*;\s*", re.IGNORECASE)

_EMPLOYMENT_MAP: dict[str, str] = {
    "permanent contract": "full_time",
    "permanent": "full_time",
    "full time": "full_time",
    "full-time": "full_time",
    "fixed-term contract": "temporary",
    "fixed term contract": "temporary",
    "fixed-term": "temporary",
    "temporary work": "temporary",
    "temporary": "temporary",
    "contract": "contract",
    "freelance": "freelance",
    "internship": "internship",
    "intern": "internship",
    "part-time work": "part_time",
    "part-time": "part_time",
    "part time": "part_time",
}

_REMOTE_TERMS = (
    "remote",
    "work from home",
    "work-from-home",
    "home-based",
    "home based",
    "telecommute",
    "telework",
    "virtual",
    "anywhere",
    #: The French terms the board occasionally reuses from the network.
    "teletravail",
    "télétravail",
    "a distance",
    "à distance",
    "en ligne",
)
_GLOBAL_TERMS = ("international", "worldwide", "global", "anywhere", "any location")

_SKILL_WORDS = frozenset(
    {
        "python",
        "java",
        "javascript",
        "sql",
        "excel",
        "sap",
        "accounting",
        "finance",
        "marketing",
        "management",
        "engineering",
        "logistics",
        "sales",
        "procurement",
        "human resources",
        "customer service",
        "data analysis",
        "project management",
        "english",
        "kinyarwanda",
        "french",
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
    common ``"Permanent contract - Fixed-term contract - Freelance"`` shape --
    return ``None`` rather than picking one, because the ad is explicitly
    offering all of them. Several values that all map to the same code are not
    ambiguous.
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
    if "rwanda" in lowered or lowered in {"rw", "rwa"}:
        return HOME_COUNTRY
    return text


def build_location(address: dict[str, Any], remote_code: str) -> str:
    """Compose a readable location from the locality, never the province list.

    ``addressRegion`` is dropped on purpose: on this board it is the list of
    provinces the ad is open to, not a region, so keeping it would repeat the
    locality and produce things like ``"Kigali, Kigali Province, Rwanda"``. The
    full value stays in ``raw_payload`` and is still used for remote detection in
    ``detect_remote``.
    """
    locality = clean_text(address.get("addressLocality"))
    country = normalize_country(address.get("addressCountry")) or HOME_COUNTRY

    if remote_code.startswith("remote") and (
        not locality
        or "remote" in locality.lower()
        or locality.startswith("/")
        or locality.lower() in {"en ligne", "online", "anywhere", "work from home"}
    ):
        locality = "Remote"

    parts: list[str] = []
    for part in (locality, country):
        if part and part not in parts:
            parts.append(part)
    return ", ".join(parts) if parts else HOME_COUNTRY


def parse_date(value: Any) -> datetime | None:  # noqa: C901 - one branch per date shape
    """Parse an ISO or day-first date into a ``datetime``."""
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

    day_first = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if day_first:
        day, month, year = (int(part) for part in day_first.groups())
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
    """Find and parse the Schema.org ``JobPosting`` block, repairing bad quotes.

    ``strict=False`` is required because the live block embeds raw newlines
    inside the description string, which the default parser rejects.
    """
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


class RwandaJobParser:
    """Extracts structured ``CleanedJob`` records from Rwandajob.com pages."""

    def parse_job(self, raw: RawRwandaJob) -> CleanedJob:  # noqa: C901 - field-by-field contract
        """Parse one Rwandajob.com detail page into a ``CleanedJob``."""
        soup = BeautifulSoup(raw.html_content, "html.parser")
        json_ld = extract_json_ld(soup)

        title = clean_text(json_ld.get("title"))
        if not title:
            heading = soup.find("h1") or soup.find("h2")
            title = clean_text(heading.get_text() if heading else "")
        if not title and soup.title:
            title = clean_text((soup.title.string or "").split("|")[0])
        if not title:
            raise RwandaJobParseError(f"no title in Rwandajob.com posting {raw.job_id} ({raw.url})")

        org = json_ld.get("hiringOrganization")
        company = ""
        logo_url: str | None = None
        if isinstance(org, dict):
            company = clean_text(org.get("name"))
            logo_url = clean_text(org.get("logo")) or None
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
            match = re.search(r"Published on\s+(\d{1,2}[./]\d{1,2}[./]\d{4})", raw.html_content)
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
            company_logo_url=logo_url,
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

    def parse_jobs(self, raw_jobs: list[RawRwandaJob]) -> list[CleanedJob]:
        """Parse a batch, skipping and logging individual failures."""
        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.parse_job(raw))
            except RwandaJobParseError as exc:
                logger.warning("Skipping Rwandajob.com posting {}: {}", raw.job_id, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Unexpected parse error for Rwandajob.com posting {}: {}",
                    raw.job_id,
                    exc,
                )
        return cleaned
