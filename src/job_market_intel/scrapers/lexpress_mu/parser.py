"""Parses a L'Express Petites Annonces ad into a ``RawLexpressMuJob``.

No JSON-LD here, so this is Tailwind-markup extraction. Measured on the live
detail page ``/annonce/20261116-1794825510`` on 2026-11-21::

    <h1 class="text-2xl font-bold w-[65%]">Pool Attendant - Azuri (Roches Noires)</h1>
    <p class="text-xs lg:text-md font-bold">Ref: 20261116-1794825510</p>
    <p class="text-sm text-gray-500">Emplois  &gt; Full-Time</p>
    <p class="mt-1 text-xs text-gray-500">16 novembre 2026</p>
    <p class="text-lg">&lt;body&gt;</p>
    <p class="text-sm text-gray-500">Localisation: Roches Noires</p>

The field contract is small and each piece has a trap:

* **Title** comes from ``<h1>``. ``<title>`` is the site-wide
  ``"L'Express Petites Annonces"`` and is never the job title.
* **Date** is French long form (``16 novembre 2026``), so it is read with a
  French month table, not the shared English ``_parse_date``.
* The **breadcrumb** and the ``Localisation:`` line share the exact class
  ``text-sm text-gray-500``; the breadcrumb is the one containing ``>`` and
  the employment type is its tail after ``>``.
* **Salary** is prose in the body (``Salary Package: MUR 27,000 - MUR 35,000
  per month.``) and only present on some ads.
* There is **no employer field**; the employer is the ad's Google-Maps query
  when present, else a conservative ``"<Name> is looking/recruiting"`` body
  heuristic, else ``"Unknown employer"``.
* Contact emails are Cloudflare-obfuscated (``__cf_email__``); the literal
  text is ``"[email protected]"`` and the real address is recovered from the
  ``data-cfemail`` attribute for audit.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import unquote_plus, urlparse

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.lexpress_mu.models import RawLexpressMuJob

from .exceptions import LexpressMuParseError

_MONTHS_FR = {
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
}
_MONTHS_ALT = "|".join(_MONTHS_FR)
_FR_DATE = re.compile(rf"(\d{{1,2}})\s+({_MONTHS_ALT})\s+(\d{{4}})", re.I)

_REF = re.compile(r"Ref:\s*(\d{8}-\d+)", re.I)

#: "MUR 27,000 - MUR 35,000" / "Rs 20,000" / "MUR 25,000 per month".
_SALARY = re.compile(
    r"(?:MUR|Rs\.?|rup(?:ee|ie)s?)\s*"
    r"(\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?:-|–|—|à|to|and)\s*(?:MUR|Rs\.?|rup(?:ee|ie)s?)?\s*(\d[\d,]*(?:\.\d+)?))?",
    re.I,
)

_PERIOD_PHRASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("per month", "monthly", "par mois", "/mois", "per mo"), "monthly"),
    (("per year", "annually", "annual", "par an", "annuel", "/an"), "yearly"),
    (("per week", "weekly", "par semaine", "/semaine"), "weekly"),
    (("per day", "daily", "par jour", "/jour"), "daily"),
    (("per hour", "hourly", "par heure", "/heure"), "hourly"),
)

_REMOTE_PHRASES = (
    "télétravail",
    "teletravail",
    "remote",
    "à distance",
    "a distance",
    "work from home",
    "home office",
    "travail à domicile",
)

_MAPS = re.compile(r"google\.com/maps/search/([^/@?]+)", re.I)
_COMPANY_BODY = re.compile(
    r"([A-Z][a-z][A-Za-z0-9&.'\- ]{1,58}?)\s+(?:is|are)\s+"
    r"(?:looking|recruiting|seeking|hiring|currently|expanding)\b"
)
_COMPANY_RECRUIT = re.compile(
    r"([A-Z][a-z][A-Za-z0-9&.'\- ]{1,58}?)\s+(?:is\s+)?"
    r"(?:recruiting|recrute|recherche|seeks|seeking)\b"
)

#: A candidate whose first word is a pronoun/determiner/verb ("We are",
#: "If you", "The company", "La compagnie") is prose, not an employer name.
#: Rejecting it keeps "Unknown employer" rather than storing a wrong name.
_STOP_FIRST = {
    "we",
    "you",
    "i",
    "they",
    "he",
    "she",
    "it",
    "our",
    "your",
    "my",
    "their",
    "the",
    "this",
    "that",
    "these",
    "those",
    "if",
    "and",
    "but",
    "or",
    "for",
    "are",
    "is",
    "la",
    "le",
    "les",
    "un",
    "une",
    "des",
    "nous",
    "vous",
    "ils",
    "elles",
    "on",
    "il",
    "elle",
    "compagnie",
    "societe",
    "société",
    "company",
    "entreprise",
    "group",
    "groupe",
    "looking",
    "urgently",
    "now",
    "currently",
    "please",
    "candidates",
    "applicants",
    "position",
    "post",
    "job",
    "vacancy",
    "offer",
    "offre",
    "poste",
    "candidat",
    "candidats",
}
_PHONE = re.compile(r"\+?\d[\d\s\-]{5,}")


def _parse_french_date(text: str) -> date | None:
    match = _FR_DATE.search(text or "")
    if not match:
        return None
    month = _MONTHS_FR.get(match.group(2).lower())
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def _extract_title(soup: BeautifulSoup) -> str | None:
    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(" ", strip=True)
        if text:
            return text
    return None


def _extract_breadcrumb(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Return ``(category, employment_type)`` from the ``Emplois > X`` line."""
    for p in soup.find_all("p"):
        classes = p.get("class") or []
        if "text-gray-500" not in classes or "text-sm" not in classes:
            continue
        text = p.get_text(" ", strip=True)
        if ">" not in text:
            continue
        parts = [part.strip() for part in text.split(">")]
        category = parts[0] or None
        employment = parts[1] if len(parts) > 1 and parts[1] else None
        return category, employment
    return None, None


def _extract_date(soup: BeautifulSoup) -> date | None:
    """The posting date is the ``text-xs text-gray-500`` <p> that is a date."""
    for p in soup.find_all("p"):
        classes = p.get("class") or []
        if "text-gray-500" not in classes or "text-xs" not in classes:
            continue
        parsed = _parse_french_date(p.get_text(" ", strip=True))
        if parsed:
            return parsed
    return None


def _extract_body(soup: BeautifulSoup) -> str:
    paragraphs = soup.find_all("p", class_="text-lg")
    return "\n\n".join(p.get_text("\n", strip=True) for p in paragraphs).strip()


def _extract_location(soup: BeautifulSoup) -> str | None:
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if text.startswith("Localisation:"):
            value = text.split(":", 1)[1].strip()
            if value:
                return value
    return None


def _extract_phone(soup: BeautifulSoup) -> str | None:
    for div in soup.find_all("div", class_=re.compile(r"font-semibold")):
        for child in div.find_all("div"):
            text = child.get_text(strip=True)
            if text and _PHONE.fullmatch(text):
                return re.sub(r"\s+", "", text)
    return None


def _decode_cf_email(encoded: str | None) -> str | None:
    """Decode Cloudflare's ``data-cfemail`` obfuscation (first byte is the key)."""
    if not encoded:
        return None
    try:
        raw = bytes.fromhex(encoded)
    except ValueError:
        return None
    if not raw:
        return None
    key = raw[0]
    try:
        return "".join(chr(byte ^ key) for byte in raw[1:])
    except ValueError:
        return None


def _extract_emails(soup: BeautifulSoup) -> list[str]:
    emails: list[str] = []
    for anchor in soup.find_all("a", class_="__cf_email__"):
        decoded = _decode_cf_email(anchor.get("data-cfemail"))
        if decoded and decoded not in emails:
            emails.append(decoded)
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if href.lower().startswith("mailto:"):
            address = href.split(":", 1)[1].split("?", 1)[0].strip()
            if address and address not in emails:
                emails.append(address)
    return emails


def _extract_maps_query(soup: BeautifulSoup) -> str | None:
    for anchor in soup.find_all("a", href=True):
        match = _MAPS.search(anchor["href"])
        if match:
            query = unquote_plus(match.group(1)).replace("+", " ").strip()
            if query:
                return query
    return None


def _guess_company(body: str, maps_query: str | None) -> tuple[str, str]:
    """Return ``(company_name, source)``; source is maps/body/none."""
    if maps_query:
        return maps_query, "maps"
    for pattern in (_COMPANY_BODY, _COMPANY_RECRUIT):
        match = pattern.search(body or "")
        if match:
            candidate = re.sub(r"\s+", " ", match.group(1)).strip(" .-")
            first = candidate.split(" ", 1)[0].lower()
            if len(candidate) >= 3 and first not in _STOP_FIRST:
                return candidate, "body"
    return "Unknown employer", "none"


def _extract_salary(body: str) -> tuple[str | None, float | None, float | None, str, bool]:
    """Return ``(salary_text, min, max, period, period_assumed)``."""
    match = _SALARY.search(body or "")
    if not match:
        return None, None, None, "monthly", False
    low = float(match.group(1).replace(",", ""))
    high = float(match.group(2).replace(",", "")) if match.group(2) else low
    if low > high:
        low, high = high, low
    window = (body or "")[max(0, match.start() - 40) : match.end() + 40].lower()
    period = "monthly"
    assumed = True
    for phrases, name in _PERIOD_PHRASES:
        if any(phrase in window for phrase in phrases):
            period = name
            assumed = False
            break
    return match.group(0).strip(), low, high, period, assumed


def _detect_remote(body: str) -> str | None:
    lowered = (body or "").lower()
    for phrase in _REMOTE_PHRASES:
        if phrase in lowered:
            return phrase
    return None


def parse_detail(
    job_id: str, html: str, url: str | None = None, listing_page: int | None = None
) -> RawLexpressMuJob:
    """Parse one ad page."""
    soup = BeautifulSoup(html or "", "html.parser")
    main = soup.find("main") or soup

    title = _extract_title(main)
    if not title:
        raise LexpressMuParseError(
            f"L'Express Petites Annonces ad {job_id} has no title in <h1>; the page "
            "was not an ad detail page (an empty title means the markup changed or "
            "the ad expired)."
        )

    category, employment_type = _extract_breadcrumb(main)
    posted_date = _extract_date(main)
    body = _extract_body(main)
    location = _extract_location(main)
    phone = _extract_phone(main)
    emails = _extract_emails(main)
    maps_query = _extract_maps_query(main)
    company_name, company_source = _guess_company(body, maps_query)

    salary_text, salary_min, salary_max, salary_period, period_assumed = _extract_salary(body)
    remote_phrase = _detect_remote(body)

    reference_match = _REF.search(main.get_text(" ", strip=True))
    reference = reference_match.group(1) if reference_match else job_id

    return RawLexpressMuJob(
        source_job_id=str(job_id),
        title=title,
        company_name=company_name,
        location=location,
        country="Mauritius",
        description=body or None,
        employment_type=employment_type,
        category=category,
        salary_text=salary_text,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_period=salary_period,
        posted_date=posted_date,
        reference=reference,
        phone=phone,
        contact_emails=emails,
        remote_phrase=remote_phrase,
        url=url,
        listing_page=listing_page,
        raw={
            "page_bytes": len(html or ""),
            "company_source": company_source,
            "maps_query": maps_query,
            "salary_period_assumed": period_assumed,
            "title_tag": soup.title.get_text(" ", strip=True) if soup.title else None,
            "url_path": urlparse(url).path if url else None,
        },
    )


class LexpressMuParser:
    """Turns a L'Express Petites Annonces detail page into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawLexpressMuJob:
        return parse_detail(job_id, html or "", url=url, listing_page=listing_page)

    def parse_many(self, records: list[dict]) -> tuple[list[RawLexpressMuJob], list[str]]:
        parsed: list[RawLexpressMuJob] = []
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
            except LexpressMuParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} L'Express Petites Annonces records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
