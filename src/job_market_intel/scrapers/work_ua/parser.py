"""Parser for work.ua (Ukraine) ad pages.

Measured shapes (2026-11-28):

* The ad page is server-rendered. The title is ``#h1-name``; the employer is
  the ``data-company-name`` attribute on the react-messenger div; the body is
  ``#job-description``; and ``data-online-at`` carries the activation timestamp
  (``2026-11-27T17:34:31+02:00``).
* Salary, address and schedule are ``<li>`` rows whose leading icon span has a
  ``title``: ``Зарплата`` ("35 000 – 50 000 грн · Після всіх відрахувань"),
  ``Адреса роботи`` ("Київ, вулиця Березняківська, 17а. 7,1 км від центру ·
  На мапі") and ``Графік роботи`` ("Повна зайнятість · Стандартний графік:
  5/2"). The address row also carries a distance block and a "На мапі" toggle,
  which are stripped so the stored location is the address alone.
* Ukrainian amounts use a non-breaking/thin space as the thousands separator
  (``35\\u202f000``) and a range separator of en dash, minus or hyphen.

No field is invented: a salary that carries no number stays undisclosed, and
employment type stays ``None`` when the schedule row names no recognised form.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from job_market_intel.cleaning.common import CleanedJob

from .exceptions import WorkUaParseError
from .models import RawWorkUaJob

#: Salary, address and schedule rows are anchored by the icon's title attribute.
_SALARY_TITLE = "Зарплата"
_ADDRESS_TITLE = "Адреса роботи"
_SCHEDULE_TITLE = "Графік роботи"

#: Currency markers -> ISO-4217. Order matters: check "грн" before "usd".
_CURRENCY_HINTS: tuple[tuple[str, str], ...] = (
    ("грн", "UAH"),
    ("₴", "UAH"),
    ("uah", "UAH"),
    ("$", "USD"),
    ("usd", "USD"),
    ("дол", "USD"),
    ("€", "EUR"),
    ("eur", "EUR"),
)

#: Period words -> ``salary.job_salaries.pay_period`` CHECK values.
_PERIOD_HINTS: tuple[tuple[str, str], ...] = (
    ("за годину", "hourly"),
    ("погодин", "hourly"),
    ("годину", "hourly"),
    ("/год", "hourly"),
    ("за день", "daily"),
    ("денн", "daily"),
    ("змін", "daily"),
    ("за тиждень", "weekly"),
    ("тиждень", "weekly"),
    ("за рік", "yearly"),
    ("річн", "yearly"),
    ("на місяць", "monthly"),
    ("в місяць", "monthly"),
    ("місяц", "monthly"),
    ("/міс", "monthly"),
)

#: Schedule phrases -> ``ref.employment_types.code``. "неповна" is checked
#: before "повна" because it contains that string.
_EMPLOYMENT_TYPES: tuple[tuple[str, str], ...] = (
    ("неповна зайнятість", "part_time"),
    ("часткова зайнятість", "part_time"),
    ("повна зайнятість", "full_time"),
    ("стажування", "internship"),
    ("практика", "internship"),
    ("тимчасов", "temporary"),
    ("контракт", "contract"),
    ("фріланс", "freelance"),
)

#: A number as the board prints it, including space thousands separators.
_NUMBER = re.compile(r"\d[\d\s\u00a0\u202f\u2009.,]*")
_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def clean_text(value: Any) -> str:
    """Unescape entities and collapse all whitespace (including NBSP)."""
    if value is None:
        return ""
    return " ".join(html.unescape(str(value)).split()).strip()


def parse_amount(token: str) -> float | None:
    """Parse one amount (``"35 000"`` -> 35000, ``"1 500,50"`` -> 1500.5)."""
    text = token.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ")
    digits = re.sub(r"[^0-9,.]", "", text)
    if not digits:
        return None
    if "," in digits and "." in digits:
        if digits.rfind(",") > digits.rfind("."):
            digits = digits.replace(".", "").replace(",", ".")
        else:
            digits = digits.replace(",", "")
    elif "," in digits:
        head, _, tail = digits.rpartition(",")
        digits = head.replace(",", "") + ("." if len(tail) != 3 else "") + tail
    elif "." in digits:
        head, _, tail = digits.rpartition(".")
        digits = head.replace(".", "") + ("." if len(tail) != 3 else "") + tail
    try:
        amount = float(digits)
    except ValueError:
        return None
    return amount if amount > 0 else None


def detect_currency(text: str) -> str:
    """The currency the salary row names, defaulting to UAH."""
    low = clean_text(text).lower()
    for marker, code in _CURRENCY_HINTS:
        if marker in low:
            return code
    return "UAH"


def detect_pay_period(text: str) -> str:
    """The pay period the salary row names; Ukrainian ads default to monthly."""
    low = clean_text(text).lower()
    for marker, period in _PERIOD_HINTS:
        if marker in low:
            return period
    return "monthly"


def parse_salary(text: str | None) -> tuple[float | None, float | None]:
    """Read up to two amounts from a salary row.

    A single number is stored as ``salary_min`` only; the row does not say it is
    a range, and inventing a maximum would be a claim the ad did not make.
    """
    raw = clean_text(text)
    if not raw:
        return None, None
    amounts = [amount for token in _NUMBER.findall(raw) if (amount := parse_amount(token))]
    if not amounts:
        return None, None
    if len(amounts) >= 2:
        low, high = sorted(amounts[:2])
        return low, high
    return amounts[0], None


def map_employment_type(text: str | None) -> str | None:
    """Map the ``Графік роботи`` row onto one ``ref.employment_types.code``."""
    low = clean_text(text).lower()
    if not low:
        return None
    for marker, code in _EMPLOYMENT_TYPES:
        if marker in low:
            return code
    return None


def detect_remote(address: str | None, title: str | None, description: str | None) -> str | None:
    """A conservative remote flag from the address, title and SEO description.

    The ad body is deliberately not scanned: "не віддалена робота" ("not a
    remote job") would otherwise be read as remote. Only the address, title and
    SEO summary are checked, a negated phrase is ignored, and a physical
    address means on-site.
    """
    haystack = " ".join(clean_text(part).lower() for part in (address, title, description) if part)
    if "гібрид" in haystack:
        return "hybrid"
    remote = "віддален" in haystack or "дистанційн" in haystack or "remote" in haystack
    negated = "не віддален" in haystack or "не дистанційн" in haystack or "not remote" in haystack
    if remote and not negated:
        return "remote_country"
    if clean_text(address):
        return "on_site"
    return None


def parse_datetime(value: Any) -> datetime | None:
    """Parse the ISO-8601 ``data-online-at`` value into a naive datetime."""
    text = clean_text(value).replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed


def extract_description(soup: BeautifulSoup) -> str:
    """The body text of ``#job-description`` with block breaks preserved."""
    node = soup.select_one("#job-description")
    if node is None:
        return ""
    for tag in node.find_all(["script", "style"]):
        tag.decompose()
    for br in node.find_all("br"):
        br.replace_with("\n")
    # Start each block on its own line; reading with an empty separator keeps
    # inline text exactly as written, so a <b> inside a sentence does not split
    # that sentence into two lines.
    for tag in node.find_all(
        ["p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "div", "tr"]
    ):
        tag.insert_before("\n")
    text = html.unescape(node.get_text(""))
    text = text.replace("\xa0", " ").replace("\u202f", " ").replace("\u2009", " ")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _row_text(soup: BeautifulSoup, icon_title: str) -> str | None:
    """The text of the ``<li>`` that carries the icon span with ``icon_title``."""
    icon = soup.find("span", attrs={"title": icon_title})
    if icon is None:
        return None
    row = icon.find_parent("li")
    if row is None:
        return None
    return clean_text(row.get_text(" ", strip=True)) or None


def extract_address(soup: BeautifulSoup) -> str | None:
    """The address row without its distance block and "На мапі" toggle."""
    icon = soup.find("span", attrs={"title": _ADDRESS_TITLE})
    if icon is None:
        return None
    row = icon.find_parent("li")
    if row is None:
        return None
    clone = BeautifulSoup(str(row), "html.parser")
    for selector in (".distance-block", "a[data-toggle='job-map']"):
        for node in clone.select(selector):
            node.decompose()
    text = clean_text(clone.get_text(" ", strip=True)).strip(" ·")
    return text or None


def _title(soup: BeautifulSoup) -> str | None:
    heading = soup.select_one("#h1-name")
    if heading is None:
        return None
    return clean_text(heading.get_text(" ", strip=True)) or None


def _company(soup: BeautifulSoup) -> str | None:
    node = soup.select_one("[data-company-name]")
    if node is None:
        return None
    return clean_text(node.get("data-company-name")) or None


def _logo_url(soup: BeautifulSoup) -> str | None:
    tag = soup.find("meta", attrs={"property": "og:image"})
    content = clean_text(tag.get("content")) if tag else ""
    if "company_logo" in content:
        return content
    return None


def _og_description(soup: BeautifulSoup) -> str | None:
    tag = soup.find("meta", attrs={"property": "og:description"})
    if tag is None:
        return None
    return clean_text(tag.get("content")) or None


class WorkUaParser:
    """Turns one work.ua listing card + ad page into a validated ``CleanedJob``."""

    def parse_job(self, raw: RawWorkUaJob) -> CleanedJob:
        """Parse one ad into a ``CleanedJob``."""
        soup = BeautifulSoup(raw.detail_html, "html.parser") if raw.detail_html else None

        title = (_title(soup) if soup is not None else None) or clean_text(raw.listing_title)
        if not title:
            raise WorkUaParseError(f"no title in work.ua ad {raw.job_id} ({raw.url})")

        company = (_company(soup) if soup is not None else None) or "Confidential Employer"
        address = extract_address(soup) if soup is not None else None
        salary_raw = _row_text(soup, _SALARY_TITLE) if soup is not None else None
        schedule_raw = _row_text(soup, _SCHEDULE_TITLE) if soup is not None else None
        body = extract_description(soup) if soup is not None else ""

        salary_min, salary_max = parse_salary(salary_raw)
        salary_disclosed = salary_min is not None or salary_max is not None
        currency = detect_currency(salary_raw or "")
        pay_period = detect_pay_period(salary_raw or "")
        employment_code = map_employment_type(schedule_raw)

        posted_raw = None
        logo_url = None
        og_description = None
        if soup is not None:
            posted_node = soup.select_one("[data-online-at]")
            posted_raw = posted_node.get("data-online-at") if posted_node else None
            logo_url = _logo_url(soup)
            og_description = _og_description(soup)
        posting_date = parse_datetime(posted_raw)

        remote_code = detect_remote(address, title, og_description)
        location = address
        if remote_code == "remote_country" and (
            not address or "віддален" in address.lower() or "дистанційн" in address.lower()
        ):
            location = "Україна"

        words = len(body.split())
        score = 0.4
        score += 0.2 if words >= 60 else (0.1 if words >= 20 else 0.0)
        score += 0.1 if company != "Confidential Employer" else 0.0
        score += 0.1 if location else 0.0
        score += 0.1 if salary_disclosed else 0.0
        score += 0.05 if posting_date else 0.0
        if not body:
            score = min(score, 0.5)

        raw_payload = {
            "url": raw.url,
            "list_position": raw.list_position,
            "list_total": raw.list_total,
            "listing_title": raw.listing_title,
            "description_source": "job-description" if body else "listing_only",
            "description_chars": len(body),
            "company_raw": company,
            "salary_raw": salary_raw,
            "schedule_raw": schedule_raw,
            "address_raw": address,
            "posted_at_raw": posted_raw,
            "og_description": og_description,
            "has_detail": soup is not None,
        }

        return CleanedJob(
            source_job_id=raw.job_id,
            job_title=title,
            company_name=company,
            company_logo_url=logo_url,
            skills=[],
            location_cleaned=location,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=body or None,
            word_count=words,
            apply_url=raw.url,
            original_url=raw.url,
            posting_date=posting_date,
            closing_date=None,
            data_quality_score=round(min(score, 0.95), 2),
            raw_payload=raw_payload,
            currency_iso_code=currency,
            pay_period=pay_period,
            employment_type_code=employment_code,
            remote_work_type_code=remote_code,
        )

    def parse_jobs(self, raw_jobs: list[RawWorkUaJob]) -> list[CleanedJob]:
        """Parse a batch, skipping and logging individual failures."""
        from loguru import logger

        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.parse_job(raw))
            except WorkUaParseError as exc:
                logger.warning("Skipping work.ua ad {}: {}", raw.job_id, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Unexpected parse error for work.ua ad {}: {}", raw.job_id, exc)
        return cleaned
