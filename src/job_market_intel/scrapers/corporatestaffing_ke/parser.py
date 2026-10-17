"""Parses a Corporate Staffing posting's HTML into a ``RawCorporateStaffingJob``.

No JSON-LD here, so this is markup extraction. The labelled rows use the shape::

    <span>Date Posted:</span> <span>16/10/2026</span>

or, in some templates, ``<strong>Label:</strong> value``. Both are read.
"""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.corporatestaffing_ke.models import RawCorporateStaffingJob

from .exceptions import CorporateStaffingParseError

# dd/mm/yyyy -- Kenyan convention, not ISO and not mm/dd/yyyy.
_DMY = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _parse_dmy(value: str | None) -> date | None:
    """Parse dd/mm/yyyy."""
    if not value:
        return None
    m = _DMY.search(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


_LABELS = {
    "date posted": "posted",
    "posted": "posted",
    "job type": "type",
    "employer": "employer",
    "salary": "salary",
    "location": "location",
    "deadline": "deadline",
    "closing date": "deadline",
    "closes": "deadline",
}


def _extract_rows(soup: BeautifulSoup) -> dict[str, str]:
    """Read the 'Label: value' rows, supporting both span and strong shapes."""
    out: dict[str, str] = {}
    # Shape 1: adjacent spans/divs where one contains a label ending in ':'.
    for el in soup.find_all(["span", "div", "p", "li", "td", "th", "strong", "b"]):
        text = el.get_text(" ", strip=True)
        if ":" not in text or len(text) > 120:
            continue
        key, _, value = text.partition(":")
        key_norm = key.strip().lower()
        if key_norm not in _LABELS:
            continue
        value = value.strip()
        if value:
            out.setdefault(_LABELS[key_norm], value)
    return out


def _extract_title(soup: BeautifulSoup) -> str | None:
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        if t:
            return t
    if soup.title:
        raw = soup.title.get_text(" ", strip=True)
        # "<Title> - Corporate Staffing Services"
        if " - " in raw:
            return raw.split(" - ", 1)[0].strip() or None
    return None


def _extract_body(soup: BeautifulSoup) -> str:
    for sel in ("main", "article", ".content", ".entry-content", "body"):
        node = soup.select_one(sel)
        if node is None:
            continue
        # Drop the labelled metadata rows and navigation chrome.
        for junk in node.select("nav, header, footer, aside, script, style"):
            junk.decompose()
        text = node.get_text(" ", strip=True)
        if text and len(text) > 200:
            return text
    return ""


def parse_detail(
    slug: str, html: str, url: str | None = None, listing_page: int | None = None
) -> RawCorporateStaffingJob:
    """Parse one posting page."""
    soup = BeautifulSoup(html or "", "html.parser")
    title = _extract_title(soup)
    if not title:
        raise CorporateStaffingParseError(
            f"Corporate Staffing posting {slug} has no title; the page was not a "
            "job detail page (an empty title means the markup changed)."
        )

    rows = _extract_rows(soup)
    body = _extract_body(soup)

    # Employer: "Employer: APA Life Assurance Company Ltd"
    employer = rows.get("employer") or "Unknown employer"
    # Location: "Location: Nairobi"
    location = rows.get("location")
    # Type: "Job Type: Full Time"
    job_type = rows.get("type")
    # Salary: "Salary: Open" / "Confidential" -- prose, not a figure.
    salary_text = rows.get("salary")

    return RawCorporateStaffingJob(
        source_job_id=str(slug),
        title=title,
        company_name=employer,
        location=location,
        country="Kenya",
        description=body or None,
        employment_type=job_type,
        salary_text=salary_text,
        posted_date=_parse_dmy(rows.get("posted")),
        closing_date=_parse_dmy(rows.get("deadline")),
        url=url,
        listing_page=listing_page,
        raw={
            "page_bytes": len(html or ""),
            "rows": rows,
            "title_tag": soup.title.get_text(" ", strip=True) if soup.title else None,
        },
    )


class CorporateStaffingParser:
    """Turns a Corporate Staffing detail page into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawCorporateStaffingJob:
        return parse_detail(job_id, html or "", url=url, listing_page=listing_page)

    def parse_many(self, records: list[dict]) -> tuple[list[RawCorporateStaffingJob], list[str]]:
        parsed: list[RawCorporateStaffingJob] = []
        issues: list[str] = []
        for rec in records:
            try:
                parsed.append(
                    self.parse(
                        str(rec.get("job_id") or ""),
                        rec.get("html"),
                        url=rec.get("url"),
                        listing_page=rec.get("listing_page"),
                    )
                )
            except CorporateStaffingParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Corporate Staffing records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
