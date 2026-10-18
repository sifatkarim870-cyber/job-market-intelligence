"""Turns a JobSearch.az posting into a :class:`RawJobSearchAzJob`.

Every selector below was read off a live rendered page on 2026-10-18; see
``client.py`` for the raw markup they were taken from.

Detail page::

    h1.vacancy__title                       job title
    h1.company__title                       employer
    .vacancy__deadline                      "Son tarix 17 noy 2026"
    .vacancy__info .company__industry a     job category
    .company__body__text .company__industry a   employer's sector
    #content_block                          the description, and nothing else

Listing card (the fallback when the detail page could not be rendered, and the
only place a posting date appears)::

    .list__item__text                       "Sürücü\\nAmper Elektrik"
    .list__item__end li (last)              "Bu gün" | "Dünən" | "16 okt"

Three traps this parser exists to avoid
---------------------------------------
1. **The first ``<h1>`` is the company, not the job.** The company block is
   rendered above the vacancy block, so ``soup.h1`` is ``Amper Elektrik``.
   Only ``.vacancy__info h1.vacancy__title`` is the job title.
2. **The date label carries no year.** "16 okt" means 16 October *this* year --
   unless that lands in the future, in which case it is last October.
3. **The whole-page text is 5,849 characters of navigation chrome** against a
   2,488-character description. Using ``body`` text puts the site's filter menu
   into every row's description.
4. **The related-jobs column renders first** and carries its own deadlines, so
   the deadline is scoped to ``.vacancy__info`` rather than selected page-wide.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.jobsearch_az.models import RawJobSearchAzJob

from .exceptions import JobSearchAzParseError

#: Azerbaijani month abbreviations as the site prints them, e.g. "16 okt".
_AZ_MONTHS = {
    "yan": 1, "fev": 2, "mar": 3, "apr": 4, "may": 5, "iyn": 6,
    "iyl": 7, "avq": 8, "sen": 9, "okt": 10, "noy": 11, "dek": 12,
}  # fmt: skip

#: Full Azerbaijani month names, accepted in either the deadline or the label.
_AZ_MONTHS_LONG = {
    "yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "iyun": 6, "iyul": 7,
    "avqust": 8, "sentyabr": 9, "oktyabr": 10, "noyabr": 11, "dekabr": 12,
}  # fmt: skip

#: "Son tarix 16 noy 2026" / "Son tarix: 16 noyabr 2026"
_DEADLINE_RE = re.compile(r"Son\s+tarix[:\s]+(\d{1,2})\s+([A-Za-zəöüğıçşƏÖÜĞIÇŞ]+)\s+(\d{4})", re.I)

#: A bare day+month with no year: "16 okt".
_LABEL_RE = re.compile(r"^(\d{1,2})\s+([A-Za-zəöüğıçşƏÖÜĞIÇŞ]{3,})\.?$")

#: Relative labels the listing uses.
_RELATIVE = {
    "bu gün": 0,  # today
    "bu günlər": 0,  # these days
    "dün": 1,  # yesterday
    "dünən": 1,  # yesterday
}

#: "3 gün əvvəl" (3 days ago) / "2 həftə əvvəl" (2 weeks ago).
_AGO_RE = re.compile(r"(\d+)\s*(gün|həftə|ay)\s*əvvəl", re.I)

_AGO_UNIT_DAYS = {"gün": 1, "həftə": 7, "ay": 30}


def _month_number(word: str) -> int | None:
    key = word.strip().lower().rstrip(".")
    month = _AZ_MONTHS.get(key[:3])
    if month:
        return month
    return _AZ_MONTHS_LONG.get(key)


def _with_year(month: int, day: int, today: date) -> date | None:
    """Pin a year-less day+month. Rolls back a year if it would be in the future."""
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return None
    if candidate > today:
        try:
            candidate = date(today.year - 1, month, day)
        except ValueError:  # pragma: no cover - Feb 29 on a non-leap year
            return None
    return candidate


def parse_posted_label(label: str | None, today: date | None = None) -> date | None:
    """Read the listing's date label. ``today`` is injected so this stays testable.

    Handles the three measured shapes -- "Bu gün", "Dünən", "16 okt" -- plus
    "N gün əvvəl". Anything else returns ``None`` rather than guessing.
    """
    today = today or date.today()
    if not label:
        return None
    text = re.sub(r"\s+", " ", label).strip()
    if not text:
        return None

    key = text.lower().rstrip(".")
    if key in _RELATIVE:
        return today - timedelta(days=_RELATIVE[key])

    if (ago := _AGO_RE.search(key)) is not None:
        amount = int(ago.group(1))
        unit = ago.group(2).lower()
        return today - timedelta(days=amount * _AGO_UNIT_DAYS[unit])

    match = _LABEL_RE.match(text)
    if match is not None:
        month = _month_number(match.group(2))
        if month is None:
            logger.debug("jobsearch_az unrecognised month in label {!r}", label)
            return None
        return _with_year(month, int(match.group(1)), today)

    logger.debug("jobsearch_az unrecognised date label {!r}", label)
    return None


def parse_deadline(text: str | None) -> date | None:
    """Read "Son tarix 16 noy 2026" (Deadline 16 Nov 2026)."""
    if not text:
        return None
    match = _DEADLINE_RE.search(text)
    if match is None:
        return None
    month = _month_number(match.group(2))
    if month is None:
        logger.debug("jobsearch_az unrecognised deadline month in {!r}", text)
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def _text(node) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _first(soup: BeautifulSoup, selector: str) -> str | None:
    node = soup.select_one(selector)
    if node is None:
        return None
    return _text(node) or None


def parse_detail(
    slug: str,
    html: str,
    *,
    url: str | None = None,
    listing_page: int | None = None,
    hints: dict[str, Any] | None = None,
    today: date | None = None,
) -> RawJobSearchAzJob:
    """Parse one rendered detail page.

    ``hints`` carries what only the listing knew -- the posting date above all,
    which the detail page does not publish -- plus a title/company fallback for
    when the detail page rendered but its hooks did not match.
    """
    hints = hints or {}
    soup = BeautifulSoup(html or "", "html.parser")

    # The company block is rendered ABOVE the vacancy block, so a bare soup.h1
    # is the employer. Only the classed hook is the job title.
    title = _first(soup, ".vacancy__info h1.vacancy__title") or hints.get("title")
    company = _first(soup, "h1.company__title") or hints.get("company")

    if not title:
        raise JobSearchAzParseError(
            f"JobSearch.az posting {slug} has no .vacancy__info h1.vacancy__title "
            "and the listing card had no title either; the markup changed."
        )

    description = _first(soup, "#content_block")
    if not description:
        raise JobSearchAzParseError(
            f"JobSearch.az posting {slug} rendered its header but no #content_block. "
            "That is a half-loaded page -- the header and the description come "
            "from two different requests -- so it is dropped rather than stored "
            "with an empty description."
        )

    # Scoped to .vacancy__info: the related-jobs column renders first and could
    # otherwise hand this posting a neighbour's deadline.
    deadline_text = _first(soup, ".vacancy__info .vacancy__deadline")
    closing = parse_deadline(deadline_text)

    return RawJobSearchAzJob(
        source_job_id=str(slug),
        title=title.strip(),
        company_name=(company or "Unknown employer").strip(),
        location=None,
        country="Azerbaijan",
        description=description,
        employment_type=None,
        industry=_first(soup, ".vacancy__info .company__industry a"),
        employer_industry=_first(soup, ".company__body__text .company__industry a"),
        posted_date=parse_posted_label(hints.get("date_label"), today),
        closing_date=closing,
        url=url,
        listing_page=listing_page,
        raw={
            "page_bytes": len(html or ""),
            "listing_title": hints.get("title"),
            "listing_company": hints.get("company"),
            "listing_date_label": hints.get("date_label"),
            "deadline_text": deadline_text,
        },
    )


class JobSearchAzParser:
    """Turns JobSearch.az records into models."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
        hints: dict[str, Any] | None = None,
        today: date | None = None,
    ) -> RawJobSearchAzJob:
        if not html:
            raise JobSearchAzParseError(
                f"JobSearch.az posting {job_id} has no rendered HTML; the detail "
                "page fetch failed. Discovery hints alone are not stored because "
                "a posting with no description is not worth a row."
            )
        return parse_detail(
            job_id, html, url=url, listing_page=listing_page, hints=hints, today=today
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawJobSearchAzJob], list[str]]:
        parsed: list[RawJobSearchAzJob] = []
        issues: list[str] = []
        for record in records:
            try:
                parsed.append(
                    self.parse(
                        str(record.get("job_id") or ""),
                        record.get("html"),
                        url=record.get("url"),
                        listing_page=record.get("listing_page"),
                        hints=record.get("hints") or {},
                    )
                )
            except JobSearchAzParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} JobSearch.az records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
