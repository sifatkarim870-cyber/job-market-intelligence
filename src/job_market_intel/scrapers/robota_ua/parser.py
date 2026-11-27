"""Parser for Robota.ua (robota.ua, Ukraine) GraphQL vacancies.

Maps one ``publishedVacancies`` item onto the shared ``CleanedJob`` contract.
No HTML scraping is involved: the API already returns structured fields and
the full HTML body. The measured shape (2026-11-28) drives the mapping:

  * ``title`` is employer-written Ukrainian/Russian; ``company.name`` the
    employer and ``company.logoUrl`` a stable Frankfurt image URL. An
    anonymous ad carries no company block, so the employer becomes
    ``"Confidential Employer"`` rather than an invented name.
  * ``salary`` is ``{amount, amountFrom, amountTo, comment, isNet, currency}``
    with ``currency`` an ISO string (``"UAH"`` observed). ``amountFrom`` and
    ``amountTo`` are the range; a single-value ad leaves both null and fills
    ``amount``. A missing ``salary`` or a non-positive bound is an honest
    "undisclosed", never a guess. Pay is quoted monthly in Ukraine.
  * ``workTypes`` are ``REMOTE`` / ``HYBRID`` / ``OFFICE``. Robota.ua is a
    Ukraine-only board, so ``REMOTE`` means remote within the country
    (``remote_country``), not global.
  * ``employmentTypes`` are ``FULL_TIME`` / ``PART_TIME`` /
    ``PROJECT_BASED`` / ``SHIFT``. ``SHIFT`` is a schedule, not an
    employment type; a multi-valued list with no single mapping becomes
    ``None`` rather than a guess, and the raw list stays in ``raw_payload``.
  * ``subrubrics`` are occupation categories (``"Cash Transactions"``,
    ``"Loans"``); they become the row's ``skills``/tags, cleaned and
    lowercased, the same role ``jobCategories`` plays for Jobvision.
  * Dates: ``firstPublishedAt`` (true original publication, 7-digit
    fractional seconds observed) is the posting date, falling back to
    ``createdAt`` then the newest-first ``sortDate``. There is no closing /
    expiry field in the payload, so ``closing_date`` stays ``None``.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text, clean_plain_text

from .exceptions import RobotaUaParseError
from .models import RawRobotaUaJob

HOME_COUNTRY = "Ukraine"
HOME_CURRENCY = "UAH"

#: ``employmentTypes`` -> ref.employment_types.code. SHIFT is deliberately
#: absent: it describes working hours, not a contract type.
_EMPLOYMENT_MAP: dict[str, str] = {
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
    "PROJECT_BASED": "contract",
}

#: ``workTypes`` -> ref.remote_work_types.code. The board is Ukraine-only, so
#: REMOTE is country-scoped.
_WORK_TYPE_MAP: dict[str, str] = {
    "OFFICE": "on_site",
    "HYBRID": "hybrid",
    "REMOTE": "remote_country",
}

#: ``2026-11-27T23:01:00.973`` and ``2022-08-02T10:43:49.7130000+03:00`` both
#: occur; Python's fromisoformat wants at most six fractional digits, so any
#: longer run is trimmed before parsing.
_LONG_FRACTION_RE = re.compile(r"(\.\d{6})\d+")


def _text(value: object) -> str | None:
    """Trimmed, cleaned non-empty string, or None."""
    if value is None:
        return None
    cleaned = clean_plain_text(str(value))
    return cleaned or None


def _money(value: object) -> int | float | None:
    """Coerce a salary bound to a positive number; ``None`` for 0/absent."""
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return int(parsed) if parsed.is_integer() else parsed


def parse_date(value: object) -> datetime | None:
    """Parse a Robota.ua ISO-8601 timestamp into a naive date-at-midnight datetime."""
    if value is None or value == "":
        return None
    text = str(value).strip().replace("Z", "+00:00")
    text = _LONG_FRACTION_RE.sub(r"\1", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return datetime(parsed.year, parsed.month, parsed.day)


def map_employment_type(values: object) -> str | None:
    """Map the ``employmentTypes`` list to one ref code, or None if ambiguous."""
    if not isinstance(values, list):
        return None
    mapped = {
        _EMPLOYMENT_MAP[str(value).strip().upper()]
        for value in values
        if str(value).strip().upper() in _EMPLOYMENT_MAP
    }
    if len(mapped) == 1:
        return mapped.pop()
    return None


def map_work_type(values: object) -> str | None:
    """Map ``workTypes`` to one ref.remote_work_types code."""
    if not isinstance(values, list):
        return None
    normalized = [str(value).strip().upper() for value in values]
    for candidate in ("REMOTE", "HYBRID", "OFFICE"):
        if candidate in normalized:
            return _WORK_TYPE_MAP[candidate]
    return None


def build_location(city_name: str | None, remote_code: str | None) -> str:
    """Build a clean location string; remote ads are labelled as such."""
    if remote_code and remote_code.startswith("remote"):
        return f"Remote, {HOME_COUNTRY}"
    if city_name:
        return f"{city_name}, {HOME_COUNTRY}"
    return HOME_COUNTRY


def extract_skills(payload: dict[str, Any]) -> list[str]:
    """Lowercased, de-duplicated subrubric names, first-seen order."""
    skills: list[str] = []
    seen: set[str] = set()
    subrubrics = payload.get("subrubrics")
    if not isinstance(subrubrics, list):
        return skills
    for subrubric in subrubrics:
        if not isinstance(subrubric, dict):
            continue
        name = _text(subrubric.get("name"))
        if not name:
            continue
        normalized = name.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        skills.append(normalized)
    return skills


def _salary(payload: dict[str, Any]) -> tuple[int | float | None, int | float | None, str]:
    """Return ``(min, max, currency)`` from the ``salary`` object."""
    salary = payload.get("salary")
    salary = salary if isinstance(salary, dict) else {}
    amount_from = _money(salary.get("amountFrom"))
    amount_to = _money(salary.get("amountTo"))
    amount = _money(salary.get("amount"))
    salary_min = amount_from if amount_from is not None else amount
    salary_max = amount_to if amount_to is not None else amount
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        salary_min, salary_max = salary_max, salary_min
    currency = salary.get("currency")
    currency = currency.strip().upper() if isinstance(currency, str) else ""
    if len(currency) != 3 or not currency.isalpha():
        currency = HOME_CURRENCY
    return salary_min, salary_max, currency


def _data_quality_score(
    *, salary_disclosed: bool, location: str | None, skills: list[str], word_count: int
) -> float:
    """The same four-signal, equally-weighted formula every cleaner uses."""
    signals = [
        salary_disclosed,
        bool(location),
        bool(skills),
        word_count >= 20,
    ]
    return round(sum(signals) / len(signals), 2)


class RobotaUaParser:
    """Turns validated Robota.ua GraphQL items into ``CleanedJob`` records."""

    def parse_job(self, raw: RawRobotaUaJob) -> CleanedJob:
        """Parse one Robota.ua vacancy into a ``CleanedJob``."""
        payload = raw.payload
        title = _text(payload.get("title"))
        if not title:
            raise RobotaUaParseError(f"no title in Robota.ua posting {raw.job_id} ({raw.url})")

        company_block = payload.get("company")
        company_block = company_block if isinstance(company_block, dict) else {}
        company_name = _text(company_block.get("name")) or "Confidential Employer"
        logo_url = _text(company_block.get("logoUrl"))

        description = clean_html_text(payload.get("fullDescription")) or clean_html_text(
            payload.get("description")
        )
        word_count = len(description.split()) if description else 0

        city_block = payload.get("city")
        city_block = city_block if isinstance(city_block, dict) else {}
        city_name = _text(city_block.get("name"))
        remote_code = map_work_type(payload.get("workTypes"))
        location = build_location(city_name, remote_code)

        employment_code = map_employment_type(payload.get("employmentTypes"))
        salary_min, salary_max, currency = _salary(payload)
        salary_disclosed = salary_min is not None or salary_max is not None

        posting_date = (
            parse_date(payload.get("firstPublishedAt"))
            or parse_date(payload.get("createdAt"))
            or parse_date(payload.get("sortDate"))
        )

        apply_url = _text(payload.get("formApplyCustomUrl")) or raw.url
        skills = extract_skills(payload)

        raw_payload = {
            "url": raw.url,
            "id": raw.job_id,
            "employment_types_raw": payload.get("employmentTypes"),
            "work_types_raw": payload.get("workTypes"),
            "schedules_raw": payload.get("schedules"),
            "salary_raw": payload.get("salary"),
            "is_net": (payload.get("salary") or {}).get("isNet")
            if isinstance(payload.get("salary"), dict)
            else None,
            "anonymous": payload.get("anonymous"),
            "is_agency": payload.get("isAgency"),
            "company_url": company_block.get("companyUrl"),
            "region": (city_block.get("region") or {}).get("name")
            if isinstance(city_block.get("region"), dict)
            else None,
            "payload": payload,
        }

        return CleanedJob(
            source_job_id=raw.job_id,
            job_title=title,
            company_name=company_name,
            company_logo_url=logo_url,
            skills=skills,
            location_cleaned=location,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=description,
            word_count=word_count,
            apply_url=apply_url,
            original_url=raw.url,
            posting_date=posting_date,
            closing_date=None,
            data_quality_score=_data_quality_score(
                salary_disclosed=salary_disclosed,
                location=location,
                skills=skills,
                word_count=word_count,
            ),
            raw_payload=raw_payload,
            currency_iso_code=currency,
            pay_period="monthly",
            employment_type_code=employment_code,
            remote_work_type_code=remote_code,
        )

    def parse_jobs(self, raw_jobs: list[RawRobotaUaJob]) -> list[CleanedJob]:
        """Parse a batch, skipping and logging individual failures."""
        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.parse_job(raw))
            except RobotaUaParseError as exc:
                logger.warning("Skipping Robota.ua posting {}: {}", raw.job_id, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Unexpected parse error for Robota.ua posting {}: {}", raw.job_id, exc
                )
        return cleaned
