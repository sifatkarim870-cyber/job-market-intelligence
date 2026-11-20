"""Parser for Jobindex listing rows and ad pages.

The board publishes two different ad pages, and the parser is explicit about
which one it read:

  * ``/jobannonce/<tid>/<slug>`` carries the full body in
    ``section.jobtext-jobad__body`` and, in its "Virksomheden tilbyder" /
    "The company offers" sidebar card, the only structured employment signals
    the board has (``Ansættelsestype``, ``Hjemmearbejde``, ``Ugentlig
    arbejdstid``). Measured on 60 sampled ads: 15 (25%) are this kind.
  * ``/vis-job/<tid>`` is the employer-paid teaser page: ~530-695 chars of the
    ad's opening paragraphs in ``div.PaidJob-inner`` and a "Se jobbet" link to
    the employer's own site. The full text is not on jobindex.dk, so no
    external page is fetched. These rows carry
    ``raw_payload["description_source"] == "vis_job_teaser"`` so a consumer can
    tell a teaser from a full body.

Metadata (title, company, area, dates) comes from the listing row first because
that is the board's own structured field; the detail page fills the gaps. On
the live board the ``area``/``addresses`` fields are empty on many employer-paid
rows, so the detail page's ``Lokation``/``jik_robotjob--area`` is a real
fallback, not decoration.

Honest absences, not guesses:

  * ``salary`` was ``null`` on all 116 sampled listing rows and the ad pages
    publish no salary field, so no amount is invented. Rows state DKK/monthly.
  * Employment type is ``None`` when the card is absent (every teaser-only ad),
    or when the card lists two or more different types. ``Fuldtid, Deltid`` is
    an explicit "either", not a full-time job.
  * ``home_workplace`` is the board's own boolean; combined with the card it
    sets ``remote_country``/``hybrid`` but never invents a global-remote job.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.cleaning.common import CleanedJob

from .exceptions import JobIndexParseError
from .models import RawJobIndexJob

HOME_COUNTRY = "Denmark"
HOME_CURRENCY = "DKK"

_EMPLOYMENT_SEPARATOR_RE = re.compile(r"\s*[,;/]\s*|\s+og\s+|\s+-\s+", re.IGNORECASE)
_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")

#: The card's own vocabulary. A token with no entry (``Fleksjob``,
#: ``Løntilskud``, ``Ikke oplyst``) is not mapped: the reference table has no
#: honest code for it and a guess would be worse than ``None``.
_EMPLOYMENT_MAP: dict[str, str] = {
    "fastansættelse": "full_time",
    "fastansat": "full_time",
    "permanent": "full_time",
    "fuldtid": "full_time",
    "full-time": "full_time",
    "full time": "full_time",
    "deltid": "part_time",
    "part-time": "part_time",
    "part time": "part_time",
    "studiejob": "part_time",
    "student job": "part_time",
    "student": "part_time",
    "tidsbegrænset": "temporary",
    "midlertidig": "temporary",
    "vikariat": "temporary",
    "temporary": "temporary",
    "fixed-term": "temporary",
    "praktik": "internship",
    "praktikant": "internship",
    "internship": "internship",
    "freelance": "freelance",
    "kontraktansættelse": "contract",
    "projektansættelse": "contract",
    "contract": "contract",
    "elevplads": "apprenticeship",
    "lærling": "apprenticeship",
    "apprenticeship": "apprenticeship",
}

_REMOTE_OFF_MARKERS = (
    "ikke oplyst",
    "tilbydes ikke",
    "not offered",
    "not disclosed",
    "ingen hjemmearbejde",
    "no remote",
)
_HYBRID_MARKERS = (
    "hybrid",
    "delvist",
    "partially remote",
    "mulighed for hjemmearbejde",
    "possibility of remote work",
    "opportunity to work from home",
)
_REMOTE_TEXT_MARKERS = (
    "100% remote",
    "100 % remote",
    "100% hjemmearbejde",
    "100 % hjemmearbejde",
    "fully remote",
    "fuldt remote",
    "remote work",
    "arbejde hjemmefra",
    "hjemmearbejde",
    "work from home",
)
_GLOBAL_MARKERS = ("worldwide", "world-wide", "anywhere", "any country")

#: The board appends this marketing suffix to a listing ``area`` when the role
#: can be done partly from home (e.g. "Nordhavn og mulighed for hjemmearbejde").
#: It is a real hybrid signal, not part of the place name.
_HOME_WORK_SUFFIX_RE = re.compile(
    r"\s*\(?\s*(?:,|\bog\b|\band\b)?\s*"
    r"(?:mulighed for hjemmearbejde|hjemmearbejde|remote work|"
    r"possibility of remote work|opportunity to work from home)\s*\)?\s*$",
    re.IGNORECASE,
)

#: Trailing call-to-action chrome the custom-layout ad body carries.
_TRAILING_CHROME = frozenset(
    {"Ansøg", "Apply", "Læs mere", "Read more", "Gem", "Se jobbet", "Ansøg nu"}
)

_MONTHS = {
    "januar": 1,
    "februar": 2,
    "marts": 3,
    "april": 4,
    "maj": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "may": 5,
    "june": 6,
    "july": 7,
    "october": 10,
}


def clean_text(value: Any) -> str:
    """Unescape entities and collapse whitespace."""
    if value is None:
        return ""
    return " ".join(html.unescape(str(value)).split()).strip()


def _employment_codes(value: Any) -> set[str]:
    """Distinct reference codes named by one card value."""
    text = clean_text(value)
    if not text:
        return set()
    codes: set[str] = set()
    for token in _EMPLOYMENT_SEPARATOR_RE.split(text):
        token = clean_text(_PARENTHETICAL_RE.sub("", token)).strip(" .,").lower()
        if not token:
            continue
        code = _EMPLOYMENT_MAP.get(token)
        if code is None:
            for key, mapped in _EMPLOYMENT_MAP.items():
                if token.startswith(key):
                    code = mapped
                    break
        if code:
            codes.add(code)
    return codes


def map_employment_type(employment_raw: Any, weekly_hours_raw: Any = None) -> str | None:
    """Map the card's employment + hours values onto one reference code.

    Weekly hours is the more specific signal (``Deltid`` on a permanent
    contract is a part-time job), so a single hours code wins. Otherwise a
    single employment-type code is used. Two or more *different* codes --
    ``Fuldtid, Deltid``, ``Freelance, Studiejob`` -- are an explicit "either"
    and become ``None`` rather than a guess.
    """
    hours_codes = _employment_codes(weekly_hours_raw)
    if len(hours_codes) == 1:
        return next(iter(hours_codes))
    employment_codes = _employment_codes(employment_raw)
    if len(employment_codes) == 1:
        return next(iter(employment_codes))
    return None


def detect_remote(remote_raw: Any, home_workplace: bool, *texts: str | None) -> str:
    """Return a ``ref.remote_work_types`` code from the card and page text."""
    raw = clean_text(remote_raw).lower()
    haystack = " ".join([raw, *(text.lower() for text in texts if text)])

    if "100" in raw and ("remote" in raw or "hjemmearbejde" in raw):
        if any(marker in haystack for marker in _GLOBAL_MARKERS):
            return "remote_global"
        return "remote_country"
    # The card's own value is the most authoritative signal, then the board's
    # home_workplace flag, and only then free text (headline/area/body).
    if any(marker in raw for marker in _HYBRID_MARKERS):
        return "hybrid"
    if any(marker in raw for marker in _REMOTE_OFF_MARKERS):
        return "on_site"
    if home_workplace:
        return "remote_country"
    if any(marker in haystack for marker in _HYBRID_MARKERS):
        return "hybrid"
    if any(marker in haystack for marker in _REMOTE_TEXT_MARKERS):
        if any(marker in haystack for marker in _GLOBAL_MARKERS):
            return "remote_global"
        return "remote_country"
    return "on_site"


def parse_date(value: Any) -> datetime | None:  # noqa: C901 - one branch per date shape
    """Parse the board's ISO, day-first or Danish/English long date shapes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None

    iso = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if iso:
        try:
            return datetime.strptime(iso.group(1), "%Y-%m-%d")
        except ValueError:
            return None

    numeric = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text)
    if numeric:
        day, month, year = (int(part) for part in numeric.groups())
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    long_form = re.search(r"(\d{1,2})\.?\s+([A-Za-zÆØÅæøå]+)\s+(\d{4})", text)
    if long_form:
        day, month_name, year = long_form.groups()
        month = _MONTHS.get(month_name.lower())
        if month:
            try:
                return datetime(int(year), month, int(day))
            except ValueError:
                return None

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _detail_metadata(soup: BeautifulSoup, page_kind: str) -> dict[str, str]:  # noqa: C901
    """Title, company, location, published date and deadline from the ad page."""
    meta = {"title": "", "company": "", "location": "", "published": "", "deadline": ""}
    if page_kind == "jobannonce":
        header = soup.select_one("header.jobtext-jobad__header")
        if header:
            heading = header.find("h1")
            if heading:
                meta["title"] = clean_text(heading.get_text(" ", strip=True))
            for item in header.select(".jobtext-jobad__metadata-item"):
                label_element = item.find("title")
                label = clean_text(label_element.get_text(" ", strip=True)) if label_element else ""
                value = clean_text(item.get_text(" ", strip=True))
                if label and value.lower().startswith(label.lower()):
                    value = clean_text(value[len(label) :]).lstrip(": ")
                key = label.rstrip(":").lower()
                if key in {"virksomhed", "company"}:
                    meta["company"] = value
                elif key in {"lokation", "location"}:
                    meta["location"] = value
        for card in soup.select("div.jobtext-sidebar-card"):
            dates = _card_pairs(card)
            if "indrykket" in dates:
                meta["published"] = dates["indrykket"]
            elif "published" in dates:
                meta["published"] = dates["published"]
            if "ansøgningsfrist" in dates:
                meta["deadline"] = dates["ansøgningsfrist"]
            elif "application deadline" in dates:
                meta["deadline"] = dates["application deadline"]
    else:
        box = soup.select_one("div.jobsearch-result")
        if box:
            company = box.select_one(".jix-toolbar-top__company")
            if company:
                meta["company"] = clean_text(company.get_text(" ", strip=True))
            heading = box.select_one("h4") or box.select_one("h1")
            if heading:
                meta["title"] = clean_text(heading.get_text(" ", strip=True))
            area = box.select_one(".jix_robotjob--area")
            if area:
                meta["location"] = clean_text(area.get_text(" ", strip=True))
            published = box.select_one(".jix-toolbar__pub")
            if published:
                meta["published"] = clean_text(published.get_text(" ", strip=True))
    return meta


def _card_pairs(card: Any) -> dict[str, str]:
    """``{label: value}`` from a sidebar card's ``dt``/``dd`` pairs."""
    pairs: dict[str, str] = {}
    for term in card.select("dt"):
        definition = term.find_next_sibling("dd")
        if definition is None:
            continue
        label = clean_text(term.get_text(" ", strip=True)).rstrip(":").strip().lower()
        if label:
            pairs[label] = clean_text(definition.get_text(" ", strip=True))
    return pairs


def offer_card(soup: BeautifulSoup) -> dict[str, str]:
    """The board's structured "company offers" signals, if the page publishes them.

    The standard layout uses a ``Virksomheden tilbyder`` / ``The company offers``
    sidebar card (``<dt>``/``<dd>``); the employer custom layouts use a
    ``div.jix-info`` block of ``<p><b>Label:</b> value</p>`` instead. Both carry
    ``Ansættelsestype``/``Hjemmearbejde``/``Ugentlig arbejdstid``.
    """
    for card in soup.select("div.jobtext-sidebar-card"):
        heading = clean_text(card.get_text(" ", strip=True)).lower()
        if "tilbyder" not in heading and "company offers" not in heading:
            continue
        return _card_pairs(card)
    info = soup.select_one("div.jix-info")
    if info is not None:
        return _info_pairs(info)
    return {}


def _info_pairs(card: Any) -> dict[str, str]:
    """``{label: value}`` from a ``jix-info`` block's ``<p><b>Label:</b> value</p>``."""
    pairs: dict[str, str] = {}
    for paragraph in card.select("p"):
        label_element = paragraph.find(["b", "strong"])
        if label_element is None:
            continue
        raw_label = clean_text(label_element.get_text(" ", strip=True))
        full = clean_text(paragraph.get_text(" ", strip=True))
        label = raw_label.rstrip(":").strip().lower()
        if not label:
            continue
        value = full[len(raw_label) :].lstrip(": ").strip() if full.startswith(raw_label) else ""
        pairs[label] = value
    return pairs


def _offer_value(offers: dict[str, str], *labels: str) -> str:
    for label in labels:
        if label in offers:
            return offers[label]
    return ""


def extract_description(  # noqa: C901 - one branch per page layout
    soup: BeautifulSoup, page_kind: str
) -> tuple[str | None, str]:
    """Return ``(description, source)`` from the fullest container available.

    Three ``jobannonce`` layouts were measured on 2026-11-20: the standard
    ``article.jobtext-jobad`` with a ``section.jobtext-jobad__body``, and two
    employer custom layouts whose bodies are ``div.jobcontent``/``div.jobtext``/
    ``div.job-box``. Custom bodies are read as text blocks (``p``/``li``/``hN``)
    so the header title, location and "Ansøg"/"Apply" chrome and the
    ``div.jix-info`` signal block do not leak into the description. The teaser
    page has none of these, so its ``div.PaidJob-inner`` paragraphs are used.
    """
    if page_kind == "jobannonce":
        for selector, source in (
            ("section.jobtext-jobad__body", "jobtext-jobad__body"),
            (".jobtext-jobad__body", "jobtext-jobad__body"),
            ("div.jobcontent", "jobcontent"),
            ("div.jobtext", "jobcontent"),
            ("div.job-box", "jobcontent"),
        ):
            element = soup.select_one(selector)
            if element is None:
                continue
            text = _blocks_text(element) or _strip_trailing_chrome(
                _normalise_block(element.get_text("\n", strip=True))
            )
            if text:
                return text, source

    box = soup.select_one("div.jobsearch-result")
    if box is not None:
        for junk in box.select(".jix_toolbar, .jix-toolbar-top, script, style"):
            junk.decompose()
        text = _blocks_text(box)
        if text:
            return text, "vis_job_teaser"
        fallback = _normalise_block(box.get_text("\n", strip=True))
        if fallback:
            return fallback, "vis_job_teaser"

    return None, "none"


def _blocks_text(container: Any) -> str | None:
    """Join a container's prose blocks, skipping its chrome and signal blocks."""
    parts: list[str] = []
    for element in container.select("p, li, h2, h3, h4"):
        if element.find_parent(class_="jix-info") is not None:
            continue
        if element.find_parent(class_="jix_onlineapplication_button") is not None:
            continue
        if element.find_parent("div", class_="jobtext-sidebar-card") is not None:
            continue
        text = clean_text(element.get_text(" ", strip=True))
        if text and text not in parts:
            parts.append(text)
    if not parts:
        return None
    return _strip_trailing_chrome("\n\n".join(parts))


def _normalise_block(text: str) -> str | None:
    cleaned = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    return cleaned or None


def _strip_trailing_chrome(text: str | None) -> str | None:
    """Drop a trailing "Ansøg"/"Læs mere" button line from a description."""
    if not text:
        return text
    lines = text.split("\n")
    while lines and lines[-1].strip() in _TRAILING_CHROME:
        lines.pop()
    stripped = "\n".join(lines).strip()
    return stripped or None


def _strip_home_work_suffix(area: str) -> str:
    """Remove the board's "... og mulighed for hjemmearbejde" marketing suffix."""
    return _HOME_WORK_SUFFIX_RE.sub("", area).strip(" ,")


def build_location(listing: dict[str, Any], detail_location: str, remote_code: str) -> str:
    """A readable place from the ad's own area, never the search page's area."""
    area = _strip_home_work_suffix(clean_text(listing.get("area")))
    addresses = listing.get("addresses")
    if not area and isinstance(addresses, list) and addresses and isinstance(addresses[0], dict):
        area = clean_text(addresses[0].get("city"))
    if not area:
        area = clean_text(detail_location)
    if not area and isinstance(addresses, list) and addresses and isinstance(addresses[0], dict):
        area = clean_text(addresses[0].get("simple_string"))

    if not area:
        return "Remote, Denmark" if remote_code.startswith("remote") else HOME_COUNTRY
    lowered = area.lower()
    if lowered in {"danmark", "denmark"} or lowered.endswith((", danmark", ", denmark")):
        return area
    return f"{area}, {HOME_COUNTRY}"


def _first_number(salary: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = salary.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def extract_salary(listing: dict[str, Any]) -> tuple[float | None, float | None, bool, str, str]:
    """Return ``(min, max, disclosed, currency, period)``.

    ``salary`` was ``null`` on every sampled row, so the defensive dict shape
    below is exercised only if the board starts publishing one. Absence is
    stored as an undisclosed DKK/monthly row, never as zero.
    """
    salary = listing.get("salary")
    if not isinstance(salary, dict) or not salary:
        return None, None, False, HOME_CURRENCY, "monthly"

    currency = clean_text(salary.get("currency")).upper() or HOME_CURRENCY
    period = clean_text(salary.get("period") or salary.get("pay_period")).lower() or "monthly"
    if period not in {"hourly", "daily", "weekly", "monthly", "yearly"}:
        period = "monthly"

    minimum = _first_number(salary, ("min", "minValue", "minimum", "from", "amount", "value"))
    maximum = _first_number(salary, ("max", "maxValue", "maximum", "to"))
    if minimum is None and maximum is None:
        return None, None, False, currency, period
    if maximum is None:
        maximum = minimum
    if minimum is None:
        minimum = maximum
    if minimum is not None and maximum is not None and minimum > maximum:
        minimum, maximum = maximum, minimum
    return minimum, maximum, True, currency, period


class JobIndexParser:
    """Extracts structured ``CleanedJob`` records from Jobindex pages."""

    def parse_job(self, raw: RawJobIndexJob) -> CleanedJob:  # noqa: C901 - field-by-field contract
        """Parse one Jobindex ad (listing row + fetched page) into a ``CleanedJob``."""
        listing = raw.listing
        soup = BeautifulSoup(raw.html_content, "html.parser")
        detail = _detail_metadata(soup, raw.page_kind)
        offers = offer_card(soup) if raw.page_kind == "jobannonce" else {}

        title = clean_text(listing.get("headline")) or detail["title"]
        if not title:
            raise JobIndexParseError(f"no title in jobindex.dk ad {raw.job_id} ({raw.ad_url})")

        company = clean_text(listing.get("companytext"))
        company_block = listing.get("company")
        if not company and isinstance(company_block, dict):
            company = clean_text(company_block.get("name"))
        if not company:
            company = detail["company"]
        if not company:
            company = "Confidential Employer"

        logo = clean_text(listing.get("listlogo_url")) or None
        if not logo and isinstance(company_block, dict):
            logo = clean_text(company_block.get("logo")) or None

        description, description_source = extract_description(soup, raw.page_kind)
        word_count = len(description.split()) if description else 0

        employment_raw = _offer_value(offers, "ansættelsestype", "employment type")
        hours_raw = _offer_value(offers, "ugentlig arbejdstid", "weekly working time")
        remote_raw = _offer_value(offers, "hjemmearbejde", "remote work")
        employment_code = map_employment_type(employment_raw, hours_raw)

        remote_code = detect_remote(
            remote_raw,
            bool(listing.get("home_workplace")),
            clean_text(listing.get("headline")),
            clean_text(listing.get("area")),
            (description or "")[:2000],
        )
        location = build_location(listing, detail["location"], remote_code)

        posting_date = (
            parse_date(listing.get("firstdate"))
            or parse_date(detail["published"])
            or parse_date(listing.get("apply_deadline"))
        )
        closing_date = (
            parse_date(listing.get("apply_deadline"))
            or parse_date(detail["deadline"])
            or parse_date(listing.get("lastdate"))
        )
        if posting_date and closing_date and closing_date < posting_date:
            closing_date = None

        salary_min, salary_max, salary_disclosed, currency, pay_period = extract_salary(listing)

        if description_source == "jobtext-jobad__body":
            quality = 0.85
        elif description_source == "jobcontent":
            quality = 0.85
        elif description_source == "vis_job_teaser":
            quality = 0.55
        else:
            quality = 0.40
        if salary_disclosed:
            quality += 0.10
        quality = round(min(quality, 1.0), 2)

        raw_payload: dict[str, Any] = {
            "url": raw.ad_url,
            "page_kind": raw.page_kind,
            "description_source": description_source,
            "listing": listing,
            "detail": detail,
            "offers": offers,
            "employment_type_raw": employment_raw,
            "weekly_hours_raw": hours_raw,
            "remote_raw": remote_raw,
            "home_workplace": listing.get("home_workplace"),
            "salary_raw": listing.get("salary"),
            "apply_url_raw": listing.get("apply_url"),
            "app_apply_url_raw": listing.get("app_apply_url"),
        }

        return CleanedJob(
            source_job_id=raw.job_id,
            job_title=title,
            company_name=company,
            company_logo_url=logo,
            skills=[],
            location_cleaned=location,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=description,
            word_count=word_count,
            apply_url=raw.ad_url,
            original_url=raw.ad_url,
            posting_date=posting_date,
            closing_date=closing_date,
            data_quality_score=quality,
            raw_payload=raw_payload,
            currency_iso_code=currency,
            pay_period=pay_period,
            employment_type_code=employment_code,
            remote_work_type_code=remote_code,
        )

    def parse_jobs(self, raw_jobs: list[RawJobIndexJob]) -> list[CleanedJob]:
        """Parse a batch, skipping and logging individual failures."""
        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.parse_job(raw))
            except JobIndexParseError as exc:
                logger.warning("Skipping jobindex.dk ad {}: {}", raw.job_id, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Unexpected parse error for jobindex.dk ad {}: {}", raw.job_id, exc)
        return cleaned
