"""Parses a Fiji Sun posting's HTML into a ``RawFijiSunJobsJob``.

No JSON-LD here, so this is markup extraction. Two measured facts drive the
design:

1. **``og:title`` / ``og:description`` are SITE-wide** -- "Fiji Sun - Your Trusted
   Source for Fiji News" -- and must not be used. Trusting them would store the
   site's name as every job's title. The title comes from ``<h1>``.

2. **The posting date is relative** -- "Posted 1 week ago" -- and the closing
   date is **absolute** -- "Closes 5 November 2026". Both live in the
   ``.border.border-neutral-300`` "Job overview" block. The relative phrase is
   converted to a calendar date (today minus the stated interval); the absolute
   one is read as a closing date.

The company is derived from the ``<h1>``'s parent text minus the ``<h1>`` itself:
``"Advertising Sales Executive (West) Fiji Sun"`` -> company ``"Fiji Sun"``.
"""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.fijisun_jobs.models import (
    RawFijiSunJobsJob,
    _parse_relative_posted,
)

from .exceptions import FijiSunJobsParseError

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_LONG_DATE = re.compile(
    r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{4})"
)

_POSTED_RE = re.compile(r"Posted\s+(\d+)\s+(day|week|month)s?\s+ago", re.I)
_CLOSES_RE = re.compile(r"Closes\s+" + _LONG_DATE.pattern, re.I)

_BODY_SELECTORS = (
    ".mt-6.whitespace-pre-line.font-serif.text-neutral-700",
    ".whitespace-pre-line.font-serif",
    "main article",
    "article",
    "main",
)

_OVERVIEW_SELECTORS = (
    ".border.border-neutral-300",
    "aside",
    "main",
)


def _parse_long_date(text: str) -> date | None:
    m = _LONG_DATE.search(text or "")
    if not m:
        return None
    month = _MONTHS.get(m.group(2).lower())
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        return None


def _extract_title_and_company(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """``<h1>`` is the title; the company is the <h1>'s parent text minus it.

    Measured: the card header renders ``"<title> <company>"`` as one element,
    with the title in an <h1> inside it. ``og:title`` is SITE-wide and must not
    be used -- it is "Fiji Sun - Your Trusted Source for Fiji News".
    """
    h1 = soup.find("h1")
    if not h1:
        return None, None
    title = h1.get_text(" ", strip=True) or None
    parent = h1.parent
    if parent is None:
        return title, None
    parent_text = parent.get_text(" ", strip=True)
    company = parent_text
    if title and parent_text.startswith(title):
        company = parent_text[len(title) :].strip()
    # A parent that is only the title gives nothing.
    return title, (company or None)


def _extract_overview(soup: BeautifulSoup) -> dict[str, str]:
    """The 'Job overview' block as label/value pairs."""
    for sel in _OVERVIEW_SELECTORS:
        node = soup.select_one(sel)
        if node is None:
            continue
        text = node.get_text(" ", strip=True)
        if "Job overview" not in text and "Posted" not in text:
            continue
        # Rows are "Label value" runs; split on known labels.
        out: dict[str, str] = {}
        labels = ("Posted", "Salary", "Openings", "Experience", "Type", "Location", "Closes")
        # Walk the text and cut at each label.
        positions = []
        for lab in labels:
            i = text.find(lab)
            if i != -1:
                positions.append((i, lab))
        positions.sort()
        for idx, (pos, lab) in enumerate(positions):
            end = positions[idx + 1][0] if idx + 1 < len(positions) else len(text)
            value = text[pos + len(lab) : end].strip()
            if value:
                out[lab.lower()] = value
        return out
    return {}


def _extract_body(soup: BeautifulSoup) -> str:
    for sel in _BODY_SELECTORS:
        node = soup.select_one(sel)
        if node is None:
            continue
        text = node.get_text(" ", strip=True)
        if text:
            return text
    return ""


def parse_detail(
    slug: str, html: str, url: str | None = None, listing_page: int | None = None
) -> RawFijiSunJobsJob:
    """Parse one posting page."""
    soup = BeautifulSoup(html or "", "html.parser")
    title, company = _extract_title_and_company(soup)
    if not title:
        raise FijiSunJobsParseError(
            f"Fiji Sun posting {slug} has no title in <h1>; the page was not a "
            "job detail page (an empty title means the markup changed)."
        )

    overview = _extract_overview(soup)
    body = _extract_body(soup)

    posted_phrase = overview.get("posted")
    posted_date = _parse_relative_posted(posted_phrase, date.today())
    closing_date = _parse_long_date(overview.get("closes", ""))

    location = overview.get("location")
    emp_type = overview.get("type")

    # Category from the breadcrumb span, if present.
    category = None
    for span in soup.select("span"):
        t = span.get_text(" ", strip=True)
        if t in (
            "Retail & Sales",
            "Other",
            "Government & Public",
            "Finance & Accounting",
            "Information Technology",
            "Healthcare",
            "Education",
            "Administration",
        ):
            category = t
            break

    return RawFijiSunJobsJob(
        source_job_id=str(slug),
        title=title,
        company_name=company or "Unknown employer",
        location=location,
        country="Fiji",
        description=body or None,
        employment_type=emp_type,
        category=category,
        posted_date=posted_date,
        closing_date=closing_date,
        posted_phrase=posted_phrase,
        url=url,
        listing_page=listing_page,
        raw={
            "page_bytes": len(html or ""),
            "overview": overview,
            "title_tag": soup.title.get_text(" ", strip=True) if soup.title else None,
            "og_title": (soup.find("meta", property="og:title") or {}).get("content"),
            "derived_posted_date": posted_date.isoformat() if posted_date else None,
        },
    )


class FijiSunJobsParser:
    """Turns a Fiji Sun detail page into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawFijiSunJobsJob:
        """Parse one posting page."""
        return parse_detail(job_id, html or "", url=url, listing_page=listing_page)

    def parse_many(self, records: list[dict]) -> tuple[list[RawFijiSunJobsJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawFijiSunJobsJob] = []
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
            except FijiSunJobsParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Fiji Sun records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
