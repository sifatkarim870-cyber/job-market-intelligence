"""Turns a Jobs.ge page into a :class:`RawJobsGeJob`.

Both page shapes were read off live renders on 2026-10-18.

The listing is a plain ``<table>``; the detail page is a table of one-cell
rows. Nothing here depends on CSS classes -- the site's are unclassed
(``<td>``, ``<tr>``) apart from ``class="vip"`` on the title anchor, so cell
*position* and known label prefixes are the only stable handles.

Traps this parser exists to avoid
---------------------------------
1. **The English detail page is a stub.** It renders the title, the employer
   and one sentence, then "See full text of this announcement in Georgian."
   A parser that reads ``/en/`` for the description stores 548 characters of
   boilerplate for every row and calls it a job description.
2. **The description is the largest row that is not a label.** The detail
   table also holds the nav chrome ("ყველა ვაკანსია" / "All Jobs"), the
   "Forward Link" row, and repeated copies of the labelled rows in an
   ``innerText`` blob. Taking the largest cell that does not start with a
   known label is the only reliable way to find the ad body.
3. **The ad body repeats the labelled rows.** ``innerText`` on the outer
   table includes them, so the description is scoped to its own ``<tr>``
   rather than to ``body``.
4. **Dates are Georgian month names with no year** -- the same trap as
   jobsearch_az, where a relative label made the derived date move.
5. **The id lives in a query parameter**, not the path.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.jobsge.models import RawJobsGeJob

from .exceptions import JobsGeParseError

#: Georgian month abbreviations, matched on the first characters because the
#: site writes them out in full and inconsistently ("ოქტომბერი" /
#: "ოქტომბერი"). Year-less, exactly like jobsearch_az.
_GE_MONTHS = {
    "იანვ": 1, "იან": 1,
    "თებ": 2,
    "მარტ": 3,
    "აპრ": 4,
    "მაის": 5,
    "ივნ": 6,
    "ივლ": 7,
    "აგვ": 8,
    "სექტ": 9,
    "ოქტ": 10,
    "ნოემ": 11,
    "დეკ": 12,
}  # fmt: skip

#: Row-label prefixes on the detail page. Each maps to a field name. Both
#: languages are listed so the parser is not tied to one of them.
_TITLE_LABELS = ("დასახელება:", "Ad title:")
_COMPANY_LABELS = ("მომწოდებელი:", "Provided By:")
_PUBLISHED_LABELS = ("გამოქვეყნდა:", "Published:")
_DEADLINE_LABELS = ("ბოლო ვადა:", "Deadline:")

#: Rows that sit in the same table and must never become a description.
_CHROWN_ROW_PREFIXES = (
    "ყველა ვაკანსია",
    "ამ ორგანიზაციის ყველა",
    "ამოსაბეჭდი ვერსია",
    "ბმულის გადაგზავნა",
    "All Jobs",
    "All Ads by this Client",
    "Printer Friendly",
    "Forward Link",
)

_ALL_LABELS = _TITLE_LABELS + _COMPANY_LABELS + _PUBLISHED_LABELS + _DEADLINE_LABELS

#: "Published: 16 October / Deadline: 16 November" -- the English listing's
#: own column headers, used when a hint comes from the table.
_ENGLISH_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "",
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=0,
    )
    if m
}

_DAY_FIRST_RE = re.compile(r"(\d{1,2})\s+([^\s]+)")
_AD_ID_RE = re.compile(r"[?&]id=(\d+)")


def parse_georgian_date(
    text: str | None,
    today: date | None = None,
    *,
    reference: date | None = None,
) -> date | None:
    """Read a year-less Georgian date such as ``16 ოქტომბერი``.

    Jobs.ge publishes no year, so one has to be inferred -- and **the right
    direction is not the same for the two dates on the page.**

    Without ``reference`` (a posting date), the year is this year, rolled back
    one year if that would put the date in the future. Nobody publishes a job
    tomorrow, so a future date means last year.

    With ``reference`` (a deadline, anchored on the posting date), the result
    is the first occurrence **on or after** it. Applying the same backward rule
    to a deadline destroys it. Measured on the first live run 2026-10-19: every
    ad read "published 16 October / deadline 16 November", the deadline resolved
    to 2026-11-16, was pushed back to **2025**-11-16 as "in the future", and was
    then dropped by the ``closing_date >= posting_date`` guard -- **6 of 6 rows
    lost their deadline.** An anchor of "on or after the posting date" reads the
    same ad correctly whether it is scraped on 19 October or on 5 December.

    ``today`` is injected so this stays testable.
    """
    today = today or date.today()
    if not text:
        return None
    match = _DAY_FIRST_RE.search(text.strip())
    if match is None:
        return None
    month = _month_from_word(match.group(2))
    if month is None:
        logger.debug("jobs.ge unrecognised month in {!r}", text)
        return None
    day = int(match.group(1))
    if reference is not None:
        for year in (reference.year, reference.year + 1):
            try:
                candidate = date(year, month, day)
            except ValueError:
                return None
            if candidate >= reference:
                return candidate
        return None
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return None
    return date(today.year - 1, month, day) if candidate > today else candidate


def _month_from_word(word: str) -> int | None:
    lowered = word.strip().lower()
    for prefix, number in _GE_MONTHS.items():
        if lowered.startswith(prefix):
            return number
    english = _ENGLISH_MONTHS.get(lowered) or _ENGLISH_MONTHS.get(lowered[:3])
    return english


def parse_english_date(
    text: str | None,
    today: date | None = None,
    *,
    reference: date | None = None,
) -> date | None:
    """Read a year-less English date such as ``16 October`` from the listing.

    The listing's own Published / Deadline columns are English, so this is the
    fallback when the Georgian row is unreadable. Same year inference, and the
    same ``reference`` rule, as :func:`parse_georgian_date`.
    """
    today = today or date.today()
    if not text:
        return None
    match = _DAY_FIRST_RE.search(text.strip())
    if match is None:
        return None
    month = _ENGLISH_MONTHS.get(match.group(2).strip().lower())
    if month is None:
        return None
    day = int(match.group(1))
    if reference is not None:
        for year in (reference.year, reference.year + 1):
            try:
                candidate = date(year, month, day)
            except ValueError:
                return None
            if candidate >= reference:
                return candidate
        return None
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return None
    return date(today.year - 1, month, day) if candidate > today else candidate


def split_published_deadline(text: str | None) -> tuple[str | None, str | None]:
    """``"გამოქვეყნდა: 16 ოქტომბერი / ბოლო ვადა: 16 ნოემბერი"``
    -> ``("16 ოქტომბერი", "16 ნოემბერი")``.

    The separator is stripped from both sides: what is left of the published
    half after the deadline label is removed is ``"16 ოქტომბერი /"``, and a
    trailing slash in a date string is exactly the kind of thing that survives
    into the raw payload and confuses the next reader.
    """
    if not text:
        return None, None
    published = text
    deadline = None
    for label in _DEADLINE_LABELS:
        if label in text:
            published, _, deadline = text.partition(label)
            break
    for label in _PUBLISHED_LABELS:
        published = published.replace(label, "")
    published = published.strip(" /").strip()
    deadline = deadline.strip(" /").strip() if deadline else None
    return published or None, deadline or None


def _cell_text(cell) -> str:
    return re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()


def _row_texts(soup: BeautifulSoup) -> list[str]:
    """Every ``<tr>``'s text, one entry per row, whitespace-collapsed."""
    out: list[str] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        text = _cell_text(tr) if cells else ""
        if text:
            out.append(text)
    return out


def _strip_label(text: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        if text.startswith(label):
            return text[len(label) :].strip()
    return None


def parse_listing(html: str, page: int = 1) -> dict[str, dict]:
    """``{ad_id: {title_en, company, published, deadline, page}}`` from the table.

    The header row's positions are used rather than fixed indices: the first
    cell is a favourite star, the second holds the title and its links, and
    the last two are the Published and Deadline columns.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    found: dict[str, dict] = {}
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 3:
            continue
        anchor = None
        for cell in cells:
            candidate = cell.find("a", href=re.compile(r"[?&]id=\d+"))
            if candidate is not None:
                anchor = candidate
                break
        if anchor is None:
            continue
        match = _AD_ID_RE.search(anchor["href"])
        if match is None:
            continue
        ad_id = match.group(1)

        title = _cell_text(anchor)
        texts = [_cell_text(c) for c in cells]
        # Drop the cell the title came from, then the company is whatever
        # short non-date cell remains.
        dates = [t for t in texts if _DAY_FIRST_RE.match(t)]
        company = next(
            (
                t
                for t in texts
                if t and t != title and t not in dates and len(t) < 90 and "\n" not in t
            ),
            None,
        )
        published = deadline = None
        if len(dates) >= 2:
            published, deadline = dates[-2], dates[-1]
        elif len(dates) == 1:
            published = dates[0]

        found.setdefault(
            ad_id,
            {
                "title_en": title or None,
                "company": company,
                "published": published,
                "deadline": deadline,
                "page": page,
            },
        )
    return found


def parse_detail(
    ad_id: str,
    html: str,
    *,
    url: str | None = None,
    listing_page: int | None = None,
    hints: dict[str, Any] | None = None,
    today: date | None = None,
) -> RawJobsGeJob:
    """Parse one rendered Georgian detail page."""
    hints = hints or {}
    soup = BeautifulSoup(html or "", "html.parser")
    rows = _row_texts(soup)

    title = company = None
    published = deadline = None
    description = None

    for text in rows:
        if (value := _strip_label(text, _TITLE_LABELS)) is not None:
            title = value or title
            continue
        if (value := _strip_label(text, _COMPANY_LABELS)) is not None:
            company = value or company
            continue
        if any(text.startswith(label) for label in _PUBLISHED_LABELS + _DEADLINE_LABELS):
            pub, dead = split_published_deadline(text)
            published = published or pub
            deadline = deadline or dead
            continue
        if text.startswith(_CHROWN_ROW_PREFIXES):
            continue
        # The ad body is the longest row that is not a label and not chrome.
        if description is None or len(text) > len(description):
            description = text

    if not title:
        raise JobsGeParseError(
            f"jobs.ge posting {ad_id} has no '{_TITLE_LABELS[0]}' row. The detail "
            "page markup changed, or this id resolved to something that is not a "
            "vacancy."
        )

    published_date = parse_georgian_date(published, today)
    if published_date is None:
        published_date = parse_english_date(hints.get("published"), today)
    # The deadline is anchored on the posting date, never on `today`: a
    # deadline is supposed to be in the future, so today's anchor sends it
    # backwards a year. See parse_georgian_date's docstring.
    closing_date = parse_georgian_date(deadline, today, reference=published_date)
    if closing_date is None:
        closing_date = parse_english_date(hints.get("deadline"), today, reference=published_date)

    return RawJobsGeJob(
        source_job_id=str(ad_id),
        title=title,
        title_en=hints.get("title_en"),
        company_name=company or hints.get("company") or "Unknown employer",
        description=description,
        location=None,
        country="Georgia",
        employment_type=None,
        posted_date=published_date,
        closing_date=closing_date,
        listing_published=hints.get("published"),
        listing_deadline=hints.get("deadline"),
        url=url,
        listing_page=listing_page,
        raw={
            "page_bytes": len(html or ""),
            "row_count": len(rows),
            "published_text": published,
            "deadline_text": deadline,
            "language": "ka",
        },
    )


class JobsGeParser:
    """Turns Jobs.ge records into models."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
        hints: dict[str, Any] | None = None,
        today: date | None = None,
    ) -> RawJobsGeJob:
        if not html:
            raise JobsGeParseError(
                f"jobs.ge posting {job_id} has no rendered HTML; the detail page was not fetched."
            )
        return parse_detail(
            job_id, html, url=url, listing_page=listing_page, hints=hints, today=today
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawJobsGeJob], list[str]]:
        parsed: list[RawJobsGeJob] = []
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
            except JobsGeParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} jobs.ge records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
