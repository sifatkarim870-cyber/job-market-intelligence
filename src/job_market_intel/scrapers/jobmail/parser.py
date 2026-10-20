"""Turns a JobMail response into a :class:`RawJobMailJob`.

Both page shapes were read off live responses on 2026-10-19.

Traps this parser exists to avoid
--------------------------------
1. **"Market Related" is a salary that is not a figure.** It sits in the same
   ``div.job-info`` as the amounts. Parsing it for digits would invent a
   number, so it is recognised and reported as an undisclosed salary instead.
2. **Rand amounts use a space for thousands and a comma for decimals** --
   ``R20 000,00 - R30 000,00`` -- and the separator is sometimes a
   non-breaking space. Both are normalised before the digits are read.
3. **The id lives in two places**: the card's ``id="results-item-7568798"``
   and the link's ``-id-7568798`` slug. Either is enough; the other is used
   to confirm it.
4. **The location's granularity varies.** ``addressLocality`` is a city on some
   postings and a province on others, with ``addressRegion`` the same value,
   so a single "town" field would be wrong half the time.
5. **The card's date may carry a non-breaking space** -- "04\\xa0September
   2026" -- and a plain ``split()`` on it produces a broken month.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.jobmail.models import (
    EMPLOYMENT_TYPES,
    NON_NUMERIC_SALARY_MARKERS,
    UNIT_TO_PAY_PERIOD,
    RawJobMailJob,
)

from .exceptions import JobMailParseError

#: ``<div class="results-item" id="results-item-7568798">``
_CARD_ID_RE = re.compile(r"^results-item-(\d+)$")
#: ``.../some-title-id-7568798``
_SLUG_ID_RE = re.compile(r"-id-(\d+)$")

#: "04 September 2026", possibly with a non-breaking space.
_CARD_DATE_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$")
_MONTHS = {
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
#: The standard three-letter abbreviations. A bare three-letter PREFIX is not
#: accepted: it cannot tell the abbreviation "Sept" from a truncated
#: "Septem", and matching the prefix would silently turn the latter into a
#: real September date.
_MONTH_ABBREVIATIONS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

#: "R20 000,00 - R30 000,00" and the single-value form "R20 000,00".
_RAND_RANGE_RE = re.compile(
    r"R\s*([\d][\d\s\u00a0.,]*?)\s*(?:-|–|to)\s*R?\s*([\d][\d\s\u00a0.,]*)",
    re.IGNORECASE,
)
_RAND_SINGLE_RE = re.compile(r"^\s*R\s*([\d][\d\s\u00a0.,]*)\s*$", re.IGNORECASE)
#: "PER MONTH", "PER HOUR", ...
_CADENCE_RE = re.compile(r"^PER\s+(MONTH|HOUR|YEAR|DAY|WEEK)$", re.IGNORECASE)

#: The board's own "there is a salary but no figure" markers, built from the
#: one set in models.py so there is a single source of truth.
_MARKER_RE = re.compile(
    "|".join(re.escape(marker) for marker in sorted(NON_NUMERIC_SALARY_MARKERS)),
    re.IGNORECASE,
)


def _text(node) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).replace("\u00a0", " ").strip()


def _unescape(value: Any) -> str:
    """Decode HTML entities in a field that came from the JSON-LD.

    The board writes the employer's name and the ad title into the
    JobPosting with entities still escaped: ``O&#x27;Brien Recruitment`` and
    ``Junior Estimator &amp; Administrator``. BeautifulSoup does not touch
    the JSON-LD block, so they arrive verbatim -- and a company called
    "O&#x27;Brien" is a different company from "O'Brien" as far as the
    corpus's company de-duplication is concerned.
    """
    if not isinstance(value, str):
        return ""
    return html.unescape(value).strip()


def parse_card_date(value: str | None) -> date | None:
    """``"04 September 2026"`` -> ``date(2026, 9, 4)``."""
    if not value:
        return None
    text = re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()
    match = _CARD_DATE_RE.match(text)
    if match is None:
        return None
    word = match.group(2).rstrip(".").lower()
    month = _MONTHS.get(word)
    if month is None:
        month = _MONTH_ABBREVIATIONS.get(word)
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def _decimal_index(text: str) -> int | None:
    """Where the decimal point is in a number, or None if it has none.

    * both ``,`` and ``.`` present -> the LAST one is the decimal point and
      the other is a thousands separator;
    * one separator type, appearing more than once -> all thousands
      ("1,000,000");
    * one separator type, appearing once -> a decimal when exactly two digits
      follow (the board's own "20 000,00") and a thousands separator when
      three do ("1,000").
    """
    commas = text.count(",")
    dots = text.count(".")
    if commas and dots:
        return max(text.rfind(","), text.rfind("."))
    if commas == 1 or dots == 1:
        index = text.rfind(",") if commas else text.rfind(".")
        if index >= 0 and len(text) - index - 1 == 2:
            return index
    return None


def parse_rand_amount(value: str | None) -> int | None:
    """``"20 000,00"`` -> ``20000``.

    South African rand writes a space for thousands and a comma for decimals.
    The separator is sometimes a non-breaking space, so every space-ish
    character is removed first.

    The decimal point is found by POSITION, not by assuming a format, because
    a blanket "strip the dots, then swap the commas" turns the US format
    "20,000.00" into **20** -- a silent thousandfold error. The rules:

    * both ``,`` and ``.`` present -> the LAST one is the decimal point and
      the other is a thousands separator;
    * one separator type, appearing more than once -> all thousands
      ("1,000,000");
    * one separator type, appearing once -> a decimal if exactly two digits
      follow (the board's own "20 000,00") and a thousands separator if
      three do ("1,000").

    Decimals are truncated, not rounded: a board that says "20 000,50" has
    published a monthly figure, and the corpus stores whole units.
    """
    if not value:
        return None
    text = value.replace("\u00a0", "").replace("\u202f", "").replace(" ", "").strip()
    if not text:
        return None

    decimal_at = _decimal_index(text)

    if decimal_at is None:
        whole, fraction = text, ""
    else:
        whole, fraction = text[:decimal_at], text[decimal_at + 1 :]

    whole = re.sub(r"[.,\s]", "", whole)
    if not whole.isdigit():
        return None
    if fraction and not fraction.isdigit():
        return None
    try:
        amount = int(whole)
        if fraction:
            amount += int(fraction) / (10 ** len(fraction))
    except ValueError:
        return None
    return int(amount)


def _clean_range(low: int | None, high: int | None) -> tuple[int | None, int | None]:
    """Drop a bound that is zero, and a ceiling below the floor.

    A zero bound is no bound, and an inverted range is not a range: the
    schema's ``salary_max >= salary_min`` CHECK would abort the insert and
    cost the whole posting. The floor is the usable figure, so it is kept and
    the offending ceiling dropped.
    """
    if low is not None and low <= 0:
        low = None
    if high is not None and high <= 0:
        high = None
    if low is not None and high is not None and high < low:
        high = None
    return low, high


def parse_card_salary(value: str | None) -> tuple[int | None, int | None, bool]:
    """``(min, max, undisclosed)`` from a card's ``div.job-info``.

    The third element is True when the board published a salary but not a
    figure -- "Market Related" -- which is not the same as publishing no
    salary at all, and the difference is kept.
    """
    if not value:
        return None, None, False
    text = re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()
    if not text:
        return None, None, False
    if _MARKER_RE.search(text):
        return None, None, True

    low = high = None
    match = _RAND_RANGE_RE.search(text)
    if match is not None:
        low = parse_rand_amount(match.group(1))
        high = parse_rand_amount(match.group(2))
    else:
        single = _RAND_SINGLE_RE.match(text)
        if single is not None:
            amount = parse_rand_amount(single.group(1))
            if amount is not None:
                low = high = amount

    if low is None and high is None:
        # A word that is not a marker and not a number: no salary, and not an
        # undisclosed one either.
        return None, None, False
    low, high = _clean_range(low, high)
    return low, high, False


def parse_cadence(value: str | None) -> str | None:
    """``"PER MONTH"`` -> ``"monthly"``."""
    if not value:
        return None
    match = _CADENCE_RE.match(re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip())
    if match is None:
        return None
    return UNIT_TO_PAY_PERIOD.get(match.group(1).upper())


def card_id(card) -> str | None:
    """The posting's id, from the card's ``id`` attribute or its link slug."""
    element_id = card.get("id") or ""
    match = _CARD_ID_RE.match(element_id)
    if match is not None:
        return match.group(1)
    link = card.select_one("a.tablinks[href]")
    if link is not None:
        match = _SLUG_ID_RE.search(link["href"] or "")
        if match is not None:
            return match.group(1)
    return None


def parse_listing(html: str, page: int = 1) -> list[dict]:
    """One dict per card on a listing page.

    The card carries the id, the date, the title, the link, a salary (or the
    words "Market Related"), the cadence, the location and the employer, so a
    listing page alone yields most of a posting -- the detail page adds the
    body, the employer's own dates and, on some postings, a numeric salary.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict] = []
    for card in soup.select("div.results-item"):
        job_id = card_id(card)
        if job_id is None:
            continue
        link = card.select_one("a.tablinks[href]")
        heading = card.select_one("h3")
        posted = card.select_one(".job-posted")
        info = card.select_one(".job-info")
        location = card.select_one(".job-location")
        company = card.select_one("span.company")

        salary_min, salary_max, undisclosed = parse_card_salary(_text(info))
        # The cadence is the div that follows .job-info inside the same
        # flex-container.
        cadence = None
        if info is not None:
            holder = info.parent
            if holder is not None:
                for sibling in holder.find_all("div", recursive=False):
                    if sibling is info:
                        continue
                    cadence = parse_cadence(_text(sibling))
                    if cadence:
                        break

        out.append(
            {
                "job_id": job_id,
                "title": _text(heading) or _text(link),
                "url": link["href"] if link is not None else None,
                "posted_text": _text(posted),
                "salary_min": salary_min,
                "salary_max": salary_max,
                "salary_undisclosed": undisclosed,
                "salary_text": _text(info),
                "pay_period": cadence,
                "card_location": _text(location),
                "card_company": _text(company),
                "page": page,
            }
        )
    return out


def _json_ld_jobposting(soup: BeautifulSoup) -> dict | None:
    """The ``JobPosting`` block, if the page has one."""
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.get_text() or ""
        if "JobPosting" not in raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    return item
    return None


def _parse_iso(value: Any) -> date | None:
    """``2026-09-04T08:55:35`` -> ``date(2026, 9, 4)``."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None


def _base_salary(data: dict) -> tuple[int | None, int | None, str | None, str | None]:
    """``(min, max, currency, pay_period)`` from the JobPosting's baseSalary."""
    salary = data.get("baseSalary")
    if not isinstance(salary, dict):
        return None, None, None, None
    currency = salary.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        currency = None
    value = salary.get("value") or {}
    if not isinstance(value, dict):
        value = {}
    period = UNIT_TO_PAY_PERIOD.get(str(value.get("unitText") or "").upper())

    def _num(key: str) -> int | None:
        raw = value.get(key)
        if raw is None:
            return None
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None

    low = _num("minValue")
    high = _num("maxValue")
    low, high = _clean_range(low, high)
    return low, high, currency, period


def _resolve_salary(
    data: dict, card: dict
) -> tuple[int | None, int | None, str | None, str | None, bool]:
    """The posting's pay, from the detail page, the card, or nowhere.

    ``(min, max, currency, pay_period, undisclosed)``.

    The detail page's ``baseSalary`` is authoritative and numeric. The card's
    ``div.job-info`` is the fallback, and it holds either a rand range or the
    words "Market Related" -- a salary that is deliberately not a figure, kept
    as its own flag rather than turned into a number.
    """
    salary_min, salary_max, currency, period = _base_salary(data)
    undisclosed = bool(card.get("salary_undisclosed"))

    if salary_min is None and card.get("salary_min") is not None:
        salary_min = card.get("salary_min")
        salary_max = card.get("salary_max")
        currency = currency or "ZAR"
        period = period or card.get("pay_period")
    if salary_min is None and not undisclosed:
        undisclosed = bool(card.get("salary_undisclosed"))
    return salary_min, salary_max, currency, period, undisclosed


def _resolve_location(data: dict) -> tuple[str | None, str | None, str | None]:
    """``(locality, region, country)`` from the JobPosting's jobLocation.

    The granularity varies: ``addressLocality`` is a city on some postings and
    a province on others, with ``addressRegion`` the same value.
    """
    place = data.get("jobLocation")
    if isinstance(place, dict):
        address = place.get("address") or {}
    else:
        address = {}
    if not isinstance(address, dict):
        address = {}

    def _clean(key: str) -> str | None:
        value = re.sub(r"\s+", " ", str(address.get(key) or "")).strip()
        return value or None

    return _clean("addressLocality"), _clean("addressRegion"), _clean("addressCountry")


def _join_location(locality: str | None, region: str | None) -> str | None:
    """``"town, county"`` -- the shape the resolver's comma fallback needs.

    The granularity varies -- a city on some postings, a province on others --
    and the region is often the same string as the locality, so an equal pair
    is not repeated.
    """
    if locality and region and locality != region:
        return f"{locality}, {region}"
    return locality or region


def parse_detail(
    job_id: str,
    html: str,
    *,
    url: str | None = None,
    listing_page: int | None = None,
    card: dict | None = None,
) -> RawJobMailJob:
    """Parse one JobMail detail page, filling gaps from the listing card."""
    card = card or {}
    soup = BeautifulSoup(html or "", "html.parser")
    data = _json_ld_jobposting(soup)
    if data is None:
        raise JobMailParseError(
            f"jobmail posting {job_id} has no schema.org JobPosting block; the "
            "page markup changed, or this is not a job detail page."
        )

    title = re.sub(r"\s+", " ", _unescape(data.get("title"))).strip()
    if not title:
        title = _unescape(card.get("title"))
    if not title:
        raise JobMailParseError(f"jobmail posting {job_id} has no title.")

    identifier = data.get("identifier")
    if isinstance(identifier, dict):
        identifier = identifier.get("value")
    resolved_id = str(identifier) if identifier else str(job_id)

    org = data.get("hiringOrganization")
    if not isinstance(org, dict):
        org = {}
    company = re.sub(r"\s+", " ", _unescape(org.get("name"))).strip()
    if not company:
        company = str(card.get("card_company") or "").strip()

    locality, region, country = _resolve_location(data)

    salary_min, salary_max, salary_currency, pay_period, undisclosed = _resolve_salary(data, card)

    employment_type = re.sub(r"\s+", " ", _unescape(data.get("employmentType"))).strip() or None
    employment_code = None
    if employment_type:
        employment_code = EMPLOYMENT_TYPES.get(employment_type.upper())
        if employment_code is None and employment_type.upper() not in EMPLOYMENT_TYPES:
            logger.warning(
                "Unrecognized JobMail employmentType {!r} -- left None.", employment_type
            )

    posted = _parse_iso(data.get("datePosted")) or parse_card_date(card.get("posted_text"))
    closing = _parse_iso(data.get("validThrough"))

    return RawJobMailJob(
        source_job_id=resolved_id,
        title=title,
        company_name=company or "Unknown employer",
        description=_unescape(data.get("description")) or None,
        location=_join_location(locality, region),
        locality=locality,
        region=region,
        country=country,
        employment_type=employment_type,
        employment_type_code=employment_code,
        industry=re.sub(r"\s+", " ", _unescape(data.get("industry"))).strip() or None,
        posted_date=posted,
        closing_date=closing,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=salary_currency,
        pay_period=pay_period,
        salary_undisclosed=undisclosed,
        url=url or data.get("url"),
        company_url=org.get("url") if isinstance(org.get("url"), str) else None,
        listing_page=listing_page,
        raw={
            "page_bytes": len(html or ""),
            "card_location": card.get("card_location"),
            "card_company": card.get("card_company"),
            "card_salary_text": card.get("salary_text"),
            "language": "en",
        },
    )


class JobMailParser:
    """Turns JobMail records into models."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
        card: dict | None = None,
    ) -> RawJobMailJob:
        if not html:
            raise JobMailParseError(
                f"jobmail posting {job_id} has no detail HTML; the detail page was not fetched."
            )
        return parse_detail(job_id, html, url=url, listing_page=listing_page, card=card)

    def parse_many(self, records: list[dict]) -> tuple[list[RawJobMailJob], list[str]]:
        parsed: list[RawJobMailJob] = []
        issues: list[str] = []
        for record in records:
            try:
                parsed.append(
                    self.parse(
                        str(record.get("job_id") or ""),
                        record.get("html"),
                        url=record.get("url"),
                        listing_page=record.get("listing_page"),
                        card=record.get("card") or {},
                    )
                )
            except JobMailParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} jobmail records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
