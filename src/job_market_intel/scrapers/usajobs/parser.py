"""Parses a USAJOBS posting into a ``RawUSAJobsJob``.

A posting arrives as two documents with no field names in common:

* the API's ``MatchedObjectDescriptor`` -- identity, organisation, salary,
  grade, category, location with coordinates, dates, QualificationSummary;
* the public job page's schema.org ``JobPosting`` JSON-LD -- ``description``,
  ``qualifications``, ``educationRequirements``, ``baseSalary``, ``jobLocation``.

Both are read, because each holds fields the other lacks. The API alone cannot
give a description (its ``PositionFormattedDescription`` is a marker object and
there is no detail endpoint); the page alone cannot give the grade, category,
sub-agency or the coordinate pair.

Written against the live API and live job pages on 2026-10-14 rather than
guessed.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.usajobs.models import RawUSAJobsJob

from .exceptions import USAJobsParseError

#: data.gov's salary interval codes -> the schema's canonical pay_period values
#: (hourly/daily/weekly/monthly/yearly, per ck_job_salaries_pay_period).
#: Emitting the API's own wording here is what made the first Job Bank run lose
#: every row, so the vocabulary is mapped explicitly rather than passed through.
_INTERVAL_TO_PERIOD = {
    "PA": "yearly",  # Per Year
    "PH": "hourly",  # Per Hour
    "PD": "daily",
    "PW": "weekly",
    "PM": "monthly",
}


def _first(value: Any) -> Any:
    """USAJOBS wraps many fields in a single-element list."""
    if isinstance(value, list) and value:
        return value[0]
    return value


def _money(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _parse_ts(value: Any) -> date | None:
    """Parse an ISO timestamp like "2026-10-01T00:00:00.0000"."""
    if not value:
        return None
    text = str(value).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not m:
        m2 = re.match(r"(\d{2})/(\d{2})/(\d{4})", text)  # JSON-LD datePosted
        if not m2:
            return None
        return date(int(m2.group(3)), int(m2.group(1)), int(m2.group(2)))
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def extract_jsonld(html: str) -> dict:
    """Pull the schema.org JobPosting block out of a job page.

    Returns an empty dict when the page has none -- a missing block degrades
    the record rather than failing it, because the API half is still valuable.
    """
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(tag.string or "{}")
        except (TypeError, ValueError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for c in candidates:
            if isinstance(c, dict) and c.get("@type") == "JobPosting":
                return c
    return {}


#: Headings inside a page-section that are chrome, not posting content: each
#: carries a "Help" toggle link, and a couple of sections are pure navigation.
_SECTION_NOISE = {"help", "videos", "similar jobs"}


def extract_page_sections(html: str) -> str:
    """Join the page's ``page-section`` blocks into one description body.

    The JSON-LD ``description`` is only a ~400-character teaser; the posting
    text actually lives in ``div.page-section`` blocks headed Overview /
    This-job-is-open-to / Duties / Requirements / Qualifications / Education,
    together ~30k characters on a typical posting. Verified against live pages
    on 2026-10-14.

    Sections are kept separate and headed, because dropping the heading loses
    the only cue that separates "Duties" from "Requirements" -- and that
    distinction is what makes the text usable for skill extraction.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    host = soup.select_one("div.apply-joa-defaults") or soup.find("main")
    if host is None:
        return ""
    parts: list[str] = []
    seen: set[str] = set()
    for section in host.select("div.page-section"):
        heading_el = section.find(["h2", "h3"])
        heading = (heading_el.get_text(" ", strip=True) if heading_el else "").strip()
        if heading.lower() in _SECTION_NOISE:
            continue
        body = section.get_text(" ", strip=True)
        # Strip the heading itself from the body so it is not duplicated.
        if heading and body.startswith(heading):
            body = body[len(heading) :].lstrip(" Help").strip()
        if len(body) < 40:
            continue
        # Each section is rendered twice -- once for desktop ("hidden
        # md:block") and once for mobile ("md:hidden") -- so the same text
        # arrives as consecutive siblings. Keyed on the body, not the
        # position, because the order of the two renderings differs.
        key = body[:400]
        if key in seen:
            continue
        seen.add(key)
        parts.append(f"{heading}\n{body}" if heading else body)
    return "\n\n".join(parts).strip()


class USAJobsParser:
    """Turns a USAJOBS descriptor (plus optional job page) into a model."""

    def parse(
        self,
        descriptor: dict,
        html: str | None = None,
        search_keyword: str | None = None,
        url: str | None = None,
    ) -> RawUSAJobsJob:
        """Parse one posting.

        Raises:
            USAJobsParseError: No PositionID or title. The id is the natural
                key, so a posting without one cannot be deduplicated, and a
                blank title is not a posting.
        """
        position_id = (descriptor.get("PositionID") or "").strip()
        title = (descriptor.get("PositionTitle") or "").strip()
        if not position_id or not title:
            raise USAJobsParseError(
                f"USAJOBS posting missing identity "
                f"(PositionID={descriptor.get('PositionID')!r}, "
                f"PositionTitle={descriptor.get('PositionTitle')!r})"
            )

        ld = extract_jsonld(html or "")

        remuneration = _first(descriptor.get("PositionRemuneration")) or {}
        salary_min = _money(remuneration.get("MinimumRange"))
        salary_max = _money(remuneration.get("MaximumRange"))
        interval = (remuneration.get("RateIntervalCode") or "").upper() or None
        salary_period = _INTERVAL_TO_PERIOD.get(interval or "")
        if salary_period is None:
            desc = (remuneration.get("Description") or "").strip()
            salary_period = _period_from_text(desc)

        location = _first(descriptor.get("PositionLocation")) or {}
        category = _first(descriptor.get("JobCategory")) or {}
        grade = _first(descriptor.get("JobGrade")) or {}
        schedule = _first(descriptor.get("PositionSchedule")) or {}
        offering = _first(descriptor.get("PositionOfferingType")) or {}

        apply_uri = descriptor.get("ApplyURI")
        if isinstance(apply_uri, list) and apply_uri:
            apply_uri = apply_uri[0]

        # Full posting text from the page sections, falling back to the JSON-LD
        # teaser when the page had no recognisable sections (e.g. the sections
        # are renamed). Either way a record is produced; a short description
        # is a quality problem, not a reason to drop a federal posting.
        description = extract_page_sections(html or "") or (ld.get("description") or "").strip()

        return RawUSAJobsJob(
            source_job_id=position_id,
            title=title,
            organization_name=descriptor.get("OrganizationName"),
            department_name=descriptor.get("DepartmentName"),
            sub_agency=descriptor.get("SubAgency"),
            location_display=descriptor.get("PositionLocationDisplay"),
            country_code=location.get("CountryCode"),
            city_name=location.get("CityName"),
            state_code=location.get("CountrySubDivisionCode"),
            latitude=_money(location.get("Latitude")),
            longitude=_money(location.get("Longitude")),
            description=description or None,
            qualification_summary=descriptor.get("QualificationSummary") or None,
            education_requirements=ld.get("educationRequirements") or None,
            job_category=category.get("Name") if isinstance(category, dict) else None,
            job_grade=grade.get("Code") if isinstance(grade, dict) else None,
            employment_type=offering.get("Code") if isinstance(offering, dict) else None,
            schedule_code=schedule.get("Code") if isinstance(schedule, dict) else None,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_period=salary_period,
            currency_iso_code="USD",
            posted_date=_parse_ts(descriptor.get("PublicationStartDate") or ld.get("datePosted")),
            closing_date=_parse_ts(
                descriptor.get("ApplicationCloseDate") or ld.get("validThrough")
            ),
            url=url or (descriptor.get("PositionURI") or "").replace(":443", "") or None,
            apply_url=apply_uri,
            search_keyword=search_keyword,
            raw={
                "interval_code": interval,
                "announcement_closing_type": descriptor.get("AnnouncementClosingType"),
                "page_bytes": len(html or ""),
            },
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawUSAJobsJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawUSAJobsJob] = []
        issues: list[str] = []
        for rec in records:
            try:
                parsed.append(
                    self.parse(
                        rec.get("descriptor") or {},
                        rec.get("html"),
                        search_keyword=rec.get("search_keyword"),
                        url=rec.get("url"),
                    )
                )
            except USAJobsParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} USAJOBS records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues


def _period_from_text(text: str) -> str | None:
    """Map a human phrase such as "Per Year" onto the schema vocabulary."""
    t = (text or "").strip().lower()
    if not t:
        return None
    # Ordered most-specific first: "per hour" contains "hour", and a naive
    # substring scan would let the shorter needle win.
    for needle, period in (
        ("per hour", "hourly"),
        ("hourly", "hourly"),
        ("/hour", "hourly"),
        ("per day", "daily"),
        ("daily", "daily"),
        ("/day", "daily"),
        ("per week", "weekly"),
        ("weekly", "weekly"),
        ("/week", "weekly"),
        ("per month", "monthly"),
        ("monthly", "monthly"),
        ("/month", "monthly"),
        ("per annum", "yearly"),
        ("per year", "yearly"),
        ("a year", "yearly"),
        ("annually", "yearly"),
        ("yearly", "yearly"),
    ):
        if needle in t:
            return period
    return None


def _to_datetime(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime(value.year, value.month, value.day)
