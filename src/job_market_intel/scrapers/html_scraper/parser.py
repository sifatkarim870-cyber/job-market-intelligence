"""Turns an HTML-scraped page into a :class:`RawHtmlScraperJob` using CSS selectors.

Parsing is driven entirely by the site's :class:`SiteConfig` selectors -- no
custom Python needed per site.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from .config import SiteConfig
from .exceptions import HtmlScraperParseError
from .models import RawHtmlScraperJob


def _select_one(soup: BeautifulSoup, selector: str):
    """Run a CSS selector, returning the first element."""
    if not selector:
        return None
    try:
        return soup.select_one(selector)
    except Exception:
        return None


def _select_attr(element, attr: str) -> str | None:
    if element is None:
        return None
    val = element.get(attr)
    return val.strip() if val else None


def _extract_text(element) -> str | None:
    if element is None:
        return None
    text = element.get_text(" ", strip=True)
    return text.strip() if text else None


def _parse_date(text: str | None) -> date | None:
    """Best-effort date parsing from various formats."""
    if not text:
        return None
    text = text.strip()
    # Try common formats
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # Try extracting just the date portion from ISO datetime
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None


import re  # noqa: E402


def parse_detail(
    source_code: str,
    site_config: SiteConfig,
    html: str,
    *,
    url: str | None = None,
    title_hint: str | None = None,
    listing_page: int | None = None,
) -> RawHtmlScraperJob:
    """Parse one HTML detail page using CSS selectors from site config."""
    soup = BeautifulSoup(html or "", "html.parser")
    sel = site_config.selectors

    title = _extract_text(_select_one(soup, sel.job_title)) or title_hint or ""
    if not title:
        raise HtmlScraperParseError(
            f"{source_code} posting has no title. The detail page markup may have changed."
        )

    company_name = _extract_text(_select_one(soup, sel.company)) or "Unknown employer"
    description = _extract_text(_select_one(soup, sel.description))
    location = _extract_text(_select_one(soup, sel.location))
    employment_type = _extract_text(_select_one(soup, sel.employment_type)) if sel.employment_type else None
    salary = _extract_text(_select_one(soup, sel.salary)) if sel.salary else None
    posted_date = _parse_date(_extract_text(_select_one(soup, sel.posted_date))) if sel.posted_date else None

    # Extract skills as a list
    skills: list[str] = []
    if sel.skills:
        skill_elems = soup.select(sel.skills)
        skills = [
            _extract_text(el) or ""
            for el in skill_elems
            if _extract_text(el)
        ]

    # Extract job ID from URL
    source_job_id = url.rsplit("/", 1)[-1] if url else ""
    if source_job_id and "/" in source_job_id:
        source_job_id = source_job_id.split("/")[-1]
    # Clean up: remove file extensions, query strings
    source_job_id = source_job_id.split("?")[0].split("#")[0]
    if not source_job_id:
        source_job_id = url or ""

    raw_payload: dict[str, Any] = {
        "selectors_used": {
            "job_title": sel.job_title,
            "company": sel.company,
            "location": sel.location,
            "description": sel.description,
            "posted_date": sel.posted_date,
            "salary": sel.salary,
            "skills": sel.skills,
        },
        "page_bytes": len(html or ""),
        "url": url,
    }
    if salary:
        raw_payload["salary_raw"] = salary

    return RawHtmlScraperJob(
        source_job_id=source_job_id,
        title=title.strip(),
        company_name=company_name.strip(),
        description=description,
        location=location,
        country=site_config.country,
        employment_type=employment_type,
        posted_date=posted_date,
        closing_date=None,  # HTML scrapers rarely have closing dates
        url=url,
        listing_page=listing_page,
        raw=raw_payload,
    )


class HtmlScraperParser:
    """Turns HTML-scraped records into models using site config."""

    def __init__(self, site_config: SiteConfig, source_code: str):
        self._site_config = site_config
        self._source_code = source_code

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
        title_hint: str | None = None,
    ) -> RawHtmlScraperJob:
        if not html:
            raise HtmlScraperParseError(
                f"{self._source_code} posting {job_id} has no HTML."
            )
        return parse_detail(
            self._source_code,
            self._site_config,
            html,
            url=url,
            listing_page=listing_page,
            title_hint=title_hint,
        )

    def parse_many(
        self, records: list[dict]
    ) -> tuple[list[RawHtmlScraperJob], list[str]]:
        parsed: list[RawHtmlScraperJob] = []
        issues: list[str] = []
        for record in records:
            try:
                parsed.append(
                    self.parse(
                        str(record.get("job_id") or ""),
                        record.get("html"),
                        url=record.get("url"),
                        listing_page=record.get("listing_page"),
                        title_hint=record.get("title_hint"),
                    )
                )
            except HtmlScraperParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} html_scraper records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
