"""Parses TopJobs listing rows and ad pages into ``RawTopJobsLkJob`` records.

Two page shapes, both measured on 2026-11-20:

**The listing row** (``<tr id="tr0" onclick="createAlert(...)">``) has seven
cells: index, job code, position+employer, a one-line teaser, opening date,
closing date, town. The title's trailing ``(20)`` is the headcount, not part
of the title -- the detail page confirms it ("Call Center Executive  (20)"
on the listing, "Call Center Executive" on the ad).

**The ad page** carries ``#position`` (title), ``#employer``, ``#remark``
(the body), ``#endDate`` (closing, ``dd/mm/yyyy``), ``#jobRefNum`` and a set
of ``.ad-status label`` values ("Full Time", "Permanent", "Onsite").

The two formats are not interchangeable: the listing writes
``Fri Nov 20 2026`` and the detail page writes ``03/12/2026``. Month names
are matched against an explicit table rather than ``strptime('%b')`` so a
Windows runner's locale cannot change the answer.

Most bodies are **images**. ``#remark`` holding an ``<img>`` and no text is
recorded as ``description_is_image=True`` and a ``None`` description: an ad
whose text cannot be read is not the same fact as an ad with no body.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.topjobs_lk.models import RawTopJobsLkJob

from .exceptions import TopJobsLkParseError

#: onclick="createAlert('0','0000000419','0001573439','0000000552','id')"
_CREATE_ALERT = re.compile(r"createAlert\('(\d+)','([^']*)','([^']*)','([^']*)'")

#: "Fri Nov 20 2026" -- the listing's own format.
_LISTING_DATE = re.compile(r"^[A-Za-z]{3}\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})$")

#: "03/12/2026" -- the detail page's own format, day-first.
_DETAIL_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")

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
}

#: Trailing headcount: "Sales  Representative  (10)".
_HEADCOUNT = re.compile(r"\s*\((\d{1,4})\)\s*$")

#: Employment labels, most specific first. "Permanent" is contract nature
#: rather than hours, so it is only used when no explicit type is present.
_EMPLOYMENT_LABELS = (
    "full time",
    "full-time",
    "part time",
    "part-time",
    "contract",
    "temporary",
    "internship",
    "intern",
    "freelance",
    "permanent",
)

#: Work-location labels. "Remote" on its own says nothing about the
#: restriction level the schema wants, so the raw label is kept and the
#: cleaner maps only the two unambiguous ones.
_WORK_MODE_LABELS = ("onsite", "on-site", "on site", "hybrid", "remote", "work from home")

#: Below this many characters, a text body is boilerplate rather than an ad.
_MIN_DESCRIPTION_CHARS = 40


def _text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_listing_date(value: str | None) -> date | None:
    """``Fri Nov 20 2026`` -> ``date(2026, 11, 20)``."""
    match = _LISTING_DATE.match(_text(value))
    if not match:
        return None
    month = _MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2)))
    except ValueError:
        return None


def parse_detail_date(value: str | None) -> date | None:
    """``03/12/2026`` -> ``date(2026, 12, 3)`` (day-first, as the board writes it)."""
    match = _DETAIL_DATE.match(_text(value))
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def split_headcount(title: str) -> tuple[str, int | None]:
    """``"Sales  Representative  (10)"`` -> ``("Sales  Representative", 10)``.

    Only a *trailing* parenthesised integer is treated as headcount; a title
    that genuinely ends in parentheses with words inside is left alone.
    """
    cleaned = _text(title)
    match = _HEADCOUNT.search(cleaned)
    if not match:
        return cleaned, None
    return _text(cleaned[: match.start()]), int(match.group(1))


def detail_url(base_url: str, rid: str, ac: str, jc: str, ec: str) -> str:
    """Build the ad URL from the four codes in the row's ``createAlert`` call."""
    path = (
        "/employer/JobAdvertismentServlet"
        f"?rid={rid}&ac={ac}&jc={jc}&ec={ec}"
        "&pg=applicant/vacancybyfunctionalarea.jsp"
    )
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def parse_listing(
    html: str, page: int = 1, base_url: str = "https://topjobs.lk"
) -> dict[str, dict]:
    """Every posting on one listing page, keyed by job code and in page order.

    A row is a posting only if it carries ``createAlert(...)`` *and* a title.
    The job code is the de-duplication key across pages.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    cards: dict[str, dict] = {}
    for row in soup.select("tr[id^='tr']"):
        match = _CREATE_ALERT.search(row.get("onclick") or "")
        if not match:
            continue
        rid, ac, jc, ec = match.groups()
        cells = row.find_all("td", recursive=False)
        if len(cells) < 7 or not jc:
            continue

        title_el = cells[2].find("h2")
        company_el = cells[2].find("h1")
        title, headcount = split_headcount(title_el.get_text(" ", strip=True) if title_el else "")
        if not title:
            continue

        cards.setdefault(
            jc,
            {
                "jc": jc,
                "rid": rid,
                "ac": ac,
                "ec": ec,
                "title": title,
                "headcount": headcount,
                "company": _text(company_el.get_text(" ", strip=True) if company_el else ""),
                "snippet": _text(cells[3].get_text(" ", strip=True)),
                "opening_raw": _text(cells[4].get_text(" ", strip=True)),
                "closing_raw": _text(cells[5].get_text(" ", strip=True)),
                "town": _text(cells[6].get_text(" ", strip=True)),
                "page": page,
                "url": detail_url(base_url, rid, ac, jc, ec),
            },
        )
    return cards


def _label_texts(soup: BeautifulSoup) -> list[str]:
    labels: list[str] = []
    for label in soup.select(".ad-status label"):
        text = _text(label.get_text(" ", strip=True))
        if text and text not in labels:
            labels.append(text)
    return labels


def _pick(labels: list[str], candidates: tuple[str, ...], *, first: bool) -> str | None:
    """Return the first (or last) label containing one of ``candidates``."""
    ordered = labels if first else list(reversed(labels))
    for label in ordered:
        low = label.lower()
        for candidate in candidates:
            if candidate in low:
                return label
    return None


def parse_detail(
    meta: dict,
    detail_html: str | None,
    *,
    url: str | None = None,
    listing_page: int | None = None,
) -> RawTopJobsLkJob:
    """Merge one ad page onto its listing row.

    ``detail_html`` may be ``None`` when the fetch failed; the listing row is
    still a usable record (title, employer, both dates, town, URL), so this
    does not raise -- the client records the fetch failure separately.
    """
    soup = BeautifulSoup(detail_html or "", "html.parser")

    title_el = soup.select_one("#position")
    title = _text(title_el.get_text(" ", strip=True)) if title_el else ""
    if not title:
        title, _ = split_headcount(meta.get("title") or "")
    if not title:
        raise TopJobsLkParseError(
            f"TopJobs job {meta.get('jc')} has no title on either the row or the ad page."
        )

    company_el = soup.select_one("#employer")
    company = _text(company_el.get_text(" ", strip=True)) if company_el else ""
    if not company:
        company = _text(meta.get("company"))

    closing_el = soup.select_one("#endDate")
    closing = parse_detail_date(closing_el.get_text(" ", strip=True) if closing_el else "")
    if closing is None:
        closing = parse_listing_date(meta.get("closing_raw"))

    remark = soup.select_one("#remark")
    body = _text(remark.get_text(" ", strip=True)) if remark else ""
    has_image = bool(remark and remark.find("img"))
    description = body if len(body) >= _MIN_DESCRIPTION_CHARS else None
    image_only = description is None and has_image

    labels = _label_texts(soup)
    employment = _pick(labels, _EMPLOYMENT_LABELS, first=True)
    work_mode = _pick(labels, _WORK_MODE_LABELS, first=True)

    return RawTopJobsLkJob(
        source_job_id=str(meta.get("jc")),
        title=title,
        company_name=company or "Unknown employer",
        headcount=meta.get("headcount"),
        listing_snippet=meta.get("snippet") or None,
        location=_text(meta.get("town")) or None,
        country="Sri Lanka",
        description=description,
        description_is_image=image_only,
        employment_type=employment,
        work_mode=work_mode,
        labels=labels,
        posted_date=parse_listing_date(meta.get("opening_raw")),
        closing_date=closing,
        url=url or meta.get("url"),
        listing_page=listing_page if listing_page is not None else meta.get("page"),
        raw={
            "listing_title": meta.get("title"),
            "listing_snippet": meta.get("snippet"),
            "town_raw": meta.get("town"),
            "opening_raw": meta.get("opening_raw"),
            "closing_raw": meta.get("closing_raw"),
            "ad_status_labels": labels,
            "description_chars": len(body),
            "description_has_image": has_image,
            "description_is_image": image_only,
            "language": "en",
        },
    )


class TopJobsLkParser:
    """Turns one listing row plus one ad page into a model."""

    def parse_listing(
        self, html: str, page: int = 1, base_url: str = "https://topjobs.lk"
    ) -> dict[str, dict]:
        return parse_listing(html, page=page, base_url=base_url)

    def parse(
        self,
        meta: dict,
        detail_html: str | None = None,
        *,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawTopJobsLkJob:
        return parse_detail(meta, detail_html, url=url, listing_page=listing_page)

    def parse_many(self, records: list[dict]) -> tuple[list[RawTopJobsLkJob], list[str]]:
        parsed: list[RawTopJobsLkJob] = []
        issues: list[str] = []
        for record in records:
            try:
                parsed.append(
                    self.parse(
                        record.get("listing") or {},
                        record.get("detail_html"),
                        url=record.get("url"),
                        listing_page=record.get("listing_page"),
                    )
                )
            except TopJobsLkParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} TopJobs records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
