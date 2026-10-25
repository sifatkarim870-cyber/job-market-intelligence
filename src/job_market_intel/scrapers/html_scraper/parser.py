"""Turns an HTML-scraped page into a :class:`RawHtmlScraperJob` using CSS selectors.

Parsing is driven entirely by the site's :class:`SiteConfig` selectors -- no
custom Python needed per site.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

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


def _meta_title(soup: BeautifulSoup) -> str | None:
    """``og:title`` is set by the page author for exactly this purpose."""
    for attr in ("property", "name"):
        tag = soup.find("meta", attrs={attr: "og:title"})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def _site_brand(site_host: str) -> str:
    host = site_host.split(":")[0].lower()
    if host.startswith("www."):
        host = host[4:]
    return host.split(".")[0] if host else ""


def _brand_names(site_host: str) -> tuple[str, ...]:
    """Both ``prace.cz`` and ``prace``: sites prefix titles with either."""
    host = site_host.split(":")[0].lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ()
    short = host.split(".")[0]
    return (host, short) if short != host else (host,)


def _usable_title(candidate: str | None, *, site_host: str = "", max_len: int = 120) -> str | None:
    """Filter page furniture masquerading as a job title.

    ``0 €`` and ``Choose language:`` are real examples of an ``h1`` on a
    posting page; both passed the earlier version because it only checked
    length, and they were stored as job titles. A leading site name is also
    stripped: prace.cz publishes ``Prace.cz - Řidič/ka C+E`` as ``og:title``.
    """
    if not candidate:
        return None
    text = candidate.strip().strip("-–—|:")
    brand = _site_brand(site_host)
    for name in _brand_names(site_host):
        for separator in (" - ", " | ", " – ", " — ", " :: "):
            prefix = f"{name}{separator}".lower()
            if text.lower().startswith(prefix):
                text = text[len(prefix) :].strip()
                break
    if not 3 <= len(text) <= max_len:
        return None
    if sum(char.isalpha() for char in text) < 3:
        return None
    from job_market_intel.validation.html_scraper_quality import NAV_TITLES

    lowered = text.lower()
    if lowered in NAV_TITLES:
        return None
    return None if brand and lowered == brand else text


def _clean_doc_title(soup: BeautifulSoup, site_host: str) -> str | None:
    """``<title>`` minus the site name: "Mesar m/z - Posao.hr" -> "Mesar m/z"."""
    tag = soup.find("title")
    text = tag.get_text(" ", strip=True) if tag else ""
    if not text:
        return None
    brand = _site_brand(site_host)
    for separator in (" | ", " – ", " — ", " - ", " :: ", " » ", " · "):
        if separator not in text:
            continue
        parts = [part.strip() for part in text.split(separator)]
        if not any(brand and brand in part.lower() for part in parts):
            continue
        kept = [part for part in parts if not (brand and brand in part.lower())]
        if kept:
            return max(kept, key=len)
    return text


def _strip_children(element, selector: str) -> None:
    """Drop badge/chip elements from a heading before its text is read."""
    if element is None or not selector:
        return
    for child in element.select(selector):
        child.decompose()


def _extract_title(
    soup: BeautifulSoup,
    selector: str,
    *,
    site_host: str = "",
    priority: str = "",
    strip_selector: str = "",
) -> tuple[str | None, str]:
    """Pick the most trustworthy title on the page.

    The default order is ``h1`` first because on a rendered posting page it is
    the job's name: ethiojobs.net's ``og:title`` is the SEO string "Event
    Organizer Jobs and Vacancies in Ethiopia | Ethiojobs." while its ``h1`` is
    "Event Organizer". minajobs.net is the opposite -- its ``h1`` is the
    category heading "OFFRES D'EMPLOIS" and its ``og:title`` is the posting's
    own title -- so the order is configurable per site.

    The generic configs use ``h1, h2, h3, [class*='title']``, and
    ``select_one`` returns whichever appears first in the document -- on
    skill.jobs that was the "Position Summary" heading, on prace.cz an
    employer blurb.

    Titles that are page furniture ("Choose language:", "0 €") are filtered
    out before any of this, so a wrong heading falls through instead of being
    stored.
    """
    order = [part.strip() for part in (priority or "h1,og:title,title-tag,selector").split(",")]

    for source in order:
        if source == "h1":
            heading = soup.find("h1")
            _strip_children(heading, strip_selector)
            candidate = _usable_title(_extract_text(heading), site_host=site_host)
        elif source == "og:title":
            candidate = _usable_title(_meta_title(soup), site_host=site_host)
        elif source == "title-tag":
            candidate = _usable_title(_clean_doc_title(soup, site_host), site_host=site_host)
        elif source == "selector":
            candidate = None
            for element in soup.select(selector) if selector else []:
                _strip_children(element, strip_selector)
                candidate = _usable_title(_extract_text(element), site_host=site_host)
                if candidate:
                    break
        else:
            continue
        if candidate:
            return candidate, source

    return None, ""


#: Class/id fragments that hold the body of a posting on boards across the
#: languages in scope. Used only when the configured selector returns nothing.
_DESCRIPTION_HINTS = (
    "job-description",
    "jobdescription",
    "job-detail",
    "jobdetail",
    "description",
    "desc",
    "detail",
    "content",
    "vacancy",
    "offer",
    "annonce",
    "descripcion",
    "beschreibung",
    "описание",
    "опис",
)

_DESCRIPTION_SELECTOR = ", ".join(
    [f"[class*='{h}']" for h in _DESCRIPTION_HINTS]
    + [f"[id*='{h}']" for h in _DESCRIPTION_HINTS]
    + ["article", "main"]
)


def _fallback_description(soup: BeautifulSoup, min_chars: int = 200) -> str | None:
    """Find the posting body when the configured selector misses it.

    Auto-generated configs guess ``.job-description, .description, ...``; on
    kosovajob, prace.cz, kalibrr and enbek.kz that selector matched nothing, so
    the row was stored with an empty description and the quality gate had to
    throw away a real posting. The largest link-light block among the usual
    container hints is a good enough second attempt.
    """
    best = ""
    for element in soup.select(_DESCRIPTION_SELECTOR):
        text = element.get_text(" ", strip=True)
        if len(text) <= len(best) or len(text) < min_chars:
            continue
        link_chars = sum(len(a.get_text(strip=True)) for a in element.find_all("a"))
        if link_chars > 0.5 * len(text):
            continue  # navigation block
        best = text
        if len(best) > 20000:
            break
    return best[:20000] or None


def _resolve_title(
    soup: BeautifulSoup,
    selector: str,
    url: str | None,
    title_hint: str | None,
    source_code: str,
    *,
    site_host: str = "",
    priority: str = "",
    strip_selector: str = "",
) -> tuple[str, str]:
    """Title + where it came from. Raises when the page names nothing."""
    title, source = _extract_title(
        soup,
        selector,
        site_host=site_host,
        priority=priority,
        strip_selector=strip_selector,
    )
    if title:
        return title, source

    hint = _usable_title(title_hint)
    if hint:
        return hint, "listing"

    # Fallback: derive a title from the URL slug before giving up, e.g.
    # "/jobs/senior-developer-role-123" -> "Senior Developer Role".
    if url:
        last_segment = url.rsplit("/", 1)[-1].split("?")[0].split("#")[0]
        slug = re.sub(r"-\d+$", "", last_segment)  # drop the trailing id
        if slug and len(slug) > 3:
            return slug.replace("-", " ").replace("_", " ").title(), "url-slug"

    raise HtmlScraperParseError(
        f"{source_code} posting has no title. The detail page markup may have changed."
    )


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

    title, title_source = _resolve_title(
        soup,
        sel.job_title,
        url,
        title_hint,
        source_code,
        site_host=urlparse(site_config.base_url).netloc if site_config.base_url else "",
        priority=site_config.title_priority,
        strip_selector=site_config.title_strip_selector,
    )

    company_name = _extract_text(_select_one(soup, sel.company)) or "Unknown employer"
    description = _extract_text(_select_one(soup, sel.description))
    if not description or len(description) < 200:
        description = _fallback_description(soup) or description
    location = _extract_text(_select_one(soup, sel.location))
    employment_type = (
        _extract_text(_select_one(soup, sel.employment_type)) if sel.employment_type else None
    )
    salary = _extract_text(_select_one(soup, sel.salary)) if sel.salary else None
    posted_date_text = (
        _extract_text(_select_one(soup, sel.posted_date)) if sel.posted_date else None
    )
    if posted_date_text and site_config.posted_date_regex:
        match = re.search(site_config.posted_date_regex, posted_date_text)
        posted_date_text = match.group(0) if match else posted_date_text
    posted_date = _parse_date(posted_date_text)

    # Extract skills as a list
    skills: list[str] = []
    if sel.skills:
        skill_elems = soup.select(sel.skills)
        skills = [_extract_text(el) or "" for el in skill_elems if _extract_text(el)]

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
        "skills": skills,
        "title_source": title_source,
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
            raise HtmlScraperParseError(f"{self._source_code} posting {job_id} has no HTML.")
        return parse_detail(
            self._source_code,
            self._site_config,
            html,
            url=url,
            listing_page=listing_page,
            title_hint=title_hint,
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawHtmlScraperJob], list[str]]:
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
