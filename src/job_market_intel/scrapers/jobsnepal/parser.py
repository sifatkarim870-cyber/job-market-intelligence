"""Parses a JobsNepal posting's HTML into a ``RawJobsNepalJob``."""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.jobsnepal.models import RawJobsNepalJob

from .exceptions import JobsNepalParseError

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_DMY = re.compile(r"(\d{1,2})\s+([A-Za-z]{3,})\.?\s*,?\s*(\d{4})")


def _parse_dmy(value: str | None) -> date | None:
    if not value:
        return None
    m = _DMY.search(value.strip())
    if not m:
        return None
    month = _MONTHS.get(m.group(2).lower()[:3])
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        return None


def _extract_title(soup: BeautifulSoup) -> str | None:
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        if t:
            return t
    if soup.title:
        raw = soup.title.get_text(" ", strip=True)
        # "<Title> - <Company> - <id> - JobsNepal"
        if " - " in raw:
            return raw.split(" - ", 1)[0].strip() or None
    return None


def _extract_company(soup: BeautifulSoup, title: str | None) -> str:
    if soup.title:
        raw = soup.title.get_text(" ", strip=True)
        # "<Title> - <Company> - <id> - JobsNepal"
        parts = [p.strip() for p in raw.split(" - ")]
        if len(parts) >= 3 and title and parts[0] == title:
            return parts[1] or "Unknown employer"
    return "Unknown employer"


def _extract_rows(soup: BeautifulSoup) -> dict[str, str]:
    out: dict[str, str] = {}
    # "Label value" runs.
    for el in soup.find_all(["div", "li", "p", "span", "td", "th", "strong", "b"]):
        text = el.get_text(" ", strip=True)
        if ":" in text and 0 < len(text) < 120:
            key, _, value = text.partition(":")
            key_norm = key.strip().lower()
            value = value.strip()
            if value:
                out.setdefault(key_norm, value)
    # "Label value" without a colon: "Posted Date 05 Oct, 2026"
    for label in (
        "Posted Date",
        "Job posted on",
        "Apply before",
        "LOCATION",
        "Position Type",
        "Experience",
        "Category",
        "Salary",
    ):
        for el in soup.find_all(string=re.compile(rf"\b{re.escape(label)}\b", re.I)):
            parent = el.parent
            if parent is None:
                continue
            txt = parent.get_text(" ", strip=True)
            if txt.lower().startswith(label.lower()):
                val = txt[len(label) :].strip()
                if val:
                    out.setdefault(label.lower(), val)
    return out


def parse_detail(
    slug: str, html: str, url: str | None = None, listing_page: int | None = None
) -> RawJobsNepalJob:
    soup = BeautifulSoup(html or "", "html.parser")
    title = _extract_title(soup)
    if not title:
        raise JobsNepalParseError(
            f"JobsNepal posting {slug} has no title; the page was not a job "
            "detail page (an empty title means the markup changed)."
        )

    rows = _extract_rows(soup)
    body = ""
    for sel in ("div-job-details", "job-details", "main", "article"):
        node = soup.select_one(sel) if "." in sel or "-" in sel else soup.find(sel)
        if node:
            body = node.get_text(" ", strip=True)
            if len(body) > 200:
                break
    if not body:
        body = soup.get_text(" ", strip=True)

    # Posted / closing dates: "Job posted on 05 Oct, 2026 Apply before 18 Oct, 2026"
    posted = None
    closing = None
    m = re.search(r"Job posted on\s+(.+?)\s+Apply before\s+(.+?)(?:\s|$)", body, re.I)
    if m:
        posted = _parse_dmy(m.group(1))
        closing = _parse_dmy(m.group(2))
    if posted is None:
        posted = _parse_dmy(rows.get("posted date"))
    if closing is None:
        m2 = re.search(r"Apply before\s+(.+?)(?:\s|$)", body, re.I)
        if m2:
            closing = _parse_dmy(m2.group(1))

    company = _extract_company(soup, title)
    location = rows.get("location")
    emp_type = rows.get("position type")
    industry = rows.get("category")
    salary_text = rows.get("salary")

    return RawJobsNepalJob(
        source_job_id=str(slug),
        title=title,
        company_name=company,
        location=location,
        country="Nepal",
        description=body or None,
        employment_type=emp_type,
        industry=industry,
        salary_text=salary_text,
        posted_date=posted,
        closing_date=closing,
        url=url,
        listing_page=listing_page,
        raw={
            "page_bytes": len(html or ""),
            "rows": rows,
            "title_tag": soup.title.get_text(" ", strip=True) if soup.title else None,
        },
    )


class JobsNepalParser:
    """Turns a JobsNepal detail page into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawJobsNepalJob:
        return parse_detail(job_id, html or "", url=url, listing_page=listing_page)

    def parse_many(self, records: list[dict]) -> tuple[list[RawJobsNepalJob], list[str]]:
        parsed: list[RawJobsNepalJob] = []
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
            except JobsNepalParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} JobsNepal records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
