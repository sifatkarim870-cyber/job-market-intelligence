"""Turns a JobsIreland.ie response into a :class:`RawJobsIrelandJob`.

Both page shapes were read off live responses on 2026-10-19.

Traps this parser exists to avoid
--------------------------------
1. **The listing title embeds the employer.** ``JobTitle`` is
   ``"Caretaker of Sports Ground (Elton) - CE Scheme - SLIABH RI LIMITED"``. A
   parser that stores it as ``job_title`` puts the employer in the title field
   and duplicates it in ``company_name``. The detail page's ``<h3>`` is the
   title alone, so the listing copy is only ever a fallback, and when it is
   used the employer is split back out.

2. **Addresses are four comma parts** and the resolver cannot read them whole.
   ``reduce_location`` below trims a mailing address to "town, county". Measured
   on 16 real addresses: 1 resolved before the reduction, 16 after.

3. **The metadata ``<li>`` elements are labelled by ``img.alt``, not by class.**
   The site's class names are almost entirely absent, but every field carries
   its own icon with a descriptive ``alt`` ("Image for Employer",
   "Image for Closing"). That is the handle used here.

4. **``alt="Image for Euro"`` is not a salary.** The text beside the euro icon
   is the label of a link to a programme-wide rates page -- "Community
   Employment Programme Rates" -- with no figure anywhere on the page.

5. **The description node carries share-button chrome.** ``.job-description``
   also holds a "Map / Share/Print / copy link / Generate PDF" block. Those
   nodes are removed from the tree before the text is read, rather than
   regexing the strings out, so a renamed button cannot leave its label behind.

6. **An empty listing is usually transient.** The board genuinely served
   "0 job found" for several minutes partway through a 78-page walk, on every
   parameter set and with no cookies set. An empty page is therefore not proof
   that the board is empty, and the client retries before believing it.
"""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.jobsireland.models import (
    VACANCY_TYPES,
    RawJobsIrelandJob,
)

from .exceptions import JobsIrelandParseError

#: The hidden inputs one listing card is made of, in document order. A card
#: starts at JobId; the rest accumulate until the next JobId.
_LISTING_FIELDS = {
    "JobId",
    "JobReference",
    "CompanyLogo",
    "JobTitle",
    "Location",
    "StartDate",
    "EndDate",
    "VacancyTypeId",
}

#: The detail page's metadata <li> icon alts, mapped to model fields.
_META_ALTS = {
    "image for employer": "company",
    "image for job ref": "reference",
    "image for location": "location",
    "image position": "positions",
    "image part time": "vacancy_type",
    "image hours per week": "hours",
    "image for euro": "rates_label",
    "image for published": "published",
    "image for closing": "closing",
}

#: Chrome inside .job-description that is not part of the ad.
_CHROME_CLASSES = ("share-group", "social-innner", "social-icons", "a2a_kit")
_CHROME_TEXT = ("Job Description", "Sector:", "Show Center Title:", "Map")

#: The scheme segment jobsireland.ie puts between title and employer in the
#: listing's JobTitle: "Caretaker (Elton) - CE Scheme - SLIABH RI LIMITED".
_SCHEME_RE = re.compile(
    r"\s+-\s+(?:CE Scheme|Community Employment|WPEP|Paid Position|"
    r"Apprenticeship|Self Employed|Job Gateway)\s+-\s+",
    re.IGNORECASE,
)
_TRAILING_SCHEME_RE = re.compile(r"\s+-\s+(?:CE Scheme|WPEP)\s*$", re.IGNORECASE)

#: "No of positions: 3", "Published On: 19 Oct 2026", "19.5 hours per week".
_POSITIONS_RE = re.compile(r"(\d+)")
_HOURS_RE = re.compile(r"([\d.]+)\s*hours")
_REF_RE = re.compile(r"Ref:\s*(\S+)")

#: An Irish Eircode, e.g. "D12 C432", "N91 E525" -- routing key + 4 alphanumerics.
_EIRCODE_RE = re.compile(r"^[A-Z]\d{2}\s?[A-Z0-9]{4}$")
#: A Dublin postal-district token, e.g. "Dublin 12".
_DUBLIN_DISTRICT_RE = re.compile(r"^Dublin\s+\d{1,2}$", re.IGNORECASE)

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_LONG_DATE_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})")
_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "",
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ],
        start=0,
    )
    if m
}


def parse_iso_date(value: str | None) -> date | None:
    """``2026-10-19T12:05:30`` -> ``date(2026, 10, 19)``.

    The listing hands back a full ISO timestamp with a time component that is
    the moment the posting was last touched, not a date of anything; only the
    date part is kept.
    """
    if not value:
        return None
    match = _ISO_DATE_RE.match(value.strip())
    if match is None:
        return parse_long_date(value)
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_long_date(value: str | None) -> date | None:
    """``Published On: 19 Oct 2026`` -> ``date(2026, 10, 19)``."""
    if not value:
        return None
    text = value.split(":", 1)[-1].strip()
    match = _LONG_DATE_RE.match(text)
    if match is None:
        return None
    month = _MONTHS.get(match.group(2)[:3].lower())
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def split_listing_title(title: str) -> tuple[str, str | None]:
    """``"Caretaker (Elton) - CE Scheme - SLIABH RI LIMITED"``.

    -> ``("Caretaker (Elton)", "SLIABH RI LIMITED")``. The middle segment is
    the programme, not part of the title and not the employer, so it is dropped
    from both. When the shape is absent the title is returned untouched with no
    employer, which is why the detail page -- not the listing -- is the
    authoritative source for both fields.
    """
    if not title:
        return "", None
    text = title.strip()
    match = _SCHEME_RE.search(text)
    if match is None:
        return _TRAILING_SCHEME_RE.sub("", text).strip(), None
    head = text[: match.start()].strip()
    tail = text[match.end() :].strip()
    return head or text, tail or None


def _reduce_without_county_prefix(parts: list[str]) -> str | None:
    """Address parts with no ``Co. <County>`` marker.

    Two shapes reach here::

        "Dublin 12"                             a bare city, optionally with a
                                                 Dublin postal district
        "<street>, <town>, <County>"             county written without "Co."

    For the second, **the town is the SECOND-to-last part, not the last** --
    the last is the county. Getting that wrong is not hypothetical: on
    ``"Stradbally Village , Stradbally, Waterford, X42 DT89"`` taking the last
    part yielded ``"Waterford"`` and lost the town entirely.
    """
    if len(parts) == 1:
        return None if _looks_like_premises(parts[0]) else parts[0]

    tail = parts[-1]
    town = next((c for c in (parts[-2], tail) if not _looks_like_premises(c)), None)
    if town is None:
        return None
    if _DUBLIN_DISTRICT_RE.match(town) or town == tail:
        return town
    # Keep the county alongside the town so a county-only match stays available
    # for towns that are not seeded.
    return f"{town}, {tail}"


def reduce_location(raw: str | None) -> str | None:
    """Trim a mailing address to "town, county" -- what the resolver can use.

    ``"COOLE HALL, Coole, Co. Westmeath, N91 E525"`` -> ``"Coole, Co. Westmeath"``.

    ``split_location_segments`` splits on ``;`` and the comma fallback inside
    ``_match_segment`` is built for a two-part "City, ST", so a four-part address
    matches nothing. Measured over 16 real addresses: 1 resolved before this
    reduction, 16 after.

    Rules, in order:
      * drop any Eircode -- it is a routing key, not a place name;
      * take the part before ``Co. <County>`` as the town, and the county as-is;
      * otherwise fall through to :func:`_reduce_without_county_prefix`;
      * a premises name alone ("COOLE HALL") is not a location and returns
        ``None`` rather than being stored as one.
    """
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return None

    # An Eircode is never a place name.
    parts = [p for p in parts if not _EIRCODE_RE.match(p.replace(" ", ""))]
    if not parts:
        return None

    county_idx = next((i for i, p in enumerate(parts) if re.match(r"^Co\.\s*[A-Z]", p)), None)
    if county_idx is None:
        return _reduce_without_county_prefix(parts)

    county = parts[county_idx]
    town = _pick_town(parts[:county_idx])
    if town is None:
        return county
    if _DUBLIN_DISTRICT_RE.match(town):
        return town
    return f"{town}, {county}"


_STREET_WORDS = (
    "road",
    "street",
    "st",
    "lane",
    "avenue",
    "ave",
    "close",
    "court",
    "square",
    "sq",
    "park",
    "house",
    "hall",
    "centre",
    "center",
    "unit",
    "centre",
    "bus",
    "bar",
    "place",
    "terrace",
    "drive",
    "quay",
    "green",
    "hill",
    "mount",
    "crescent",
    "walk",
    "point",
    "shop",
    "mills",
    "street",
)


def _looks_like_premises(text: str) -> bool:
    """True for a building or organisation name rather than a settlement."""
    lowered = text.lower()
    if any(
        word in lowered
        for word in (
            " ltd",
            " limited",
            " clg",
            " company",
            " centre",
            " center",
            " church",
            " school",
            " hospital",
        )
    ):
        return True
    tokens = [t.strip(".,'").lower() for t in lowered.split()]
    return sum(1 for t in tokens if t in _STREET_WORDS) > 0


def _pick_town(parts: list[str]) -> str | None:
    """The town from the parts BEFORE an explicit ``Co. <County>``.

    Here the county is already separated out, so the town is simply the last
    part that is not a premises or street name.
    """
    for part in reversed(parts):
        if _looks_like_premises(part):
            continue
        return part
    return None


def parse_listing(html: str, page: int = 1) -> dict[str, dict]:
    """``{ad_id: {...}}`` from the listing's hidden inputs.

    The inputs are flat siblings -- one JobId, one JobTitle, one Location... in
    job order -- so they are grouped per card by starting a new record at each
    ``JobId`` rather than by looking for a per-card container. The markup has no
    card element to hang them off: the visible ``div.job-detail-right-box`` is
    the *right-hand* half of a row, and the hidden inputs sit outside it.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    records: dict[str, dict] = {}
    current: dict | None = None
    for el in soup.select("input[type=hidden][id]"):
        field = el.get("id")
        if field not in _LISTING_FIELDS:
            continue
        value = el.get("value") or ""
        if field == "JobId":
            if current and current.get("JobId"):
                records[current["JobId"]] = current
            current = {"page": page}
        if current is not None:
            current[field] = value
    if current and current.get("JobId"):
        records[current["JobId"]] = current
    return records


def _detail_meta(soup: BeautifulSoup) -> dict[str, str]:
    """The ``ul.job-detail_list`` fields, keyed by their icon's ``alt``."""
    out: dict[str, str] = {}
    for li in soup.select("ul.job-detail_list li"):
        img = li.find("img")
        alt = (img.get("alt") if img is not None else "") or ""
        field = _META_ALTS.get(alt.strip().lower())
        if field is None:
            continue
        text = re.sub(r"\s+", " ", li.get_text(" ", strip=True)).strip()
        if text and field not in out:
            out[field] = text
    return out


def _clean_description(soup: BeautifulSoup) -> str | None:
    """.job-description with the share block removed, not string-matched.

    The chrome is deleted from the tree first, so a button that is renamed
    leaves nothing behind; a substring filter would keep the old words.
    """
    node = soup.select_one(".job-description")
    if node is None:
        return None
    for element in list(node.select(", ".join(f".{c}" for c in _CHROME_CLASSES))):
        element.decompose()
    lines: list[str] = []
    for raw_line in node.get_text("\n", strip=True).split("\n"):
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line or line in _CHROME_TEXT:
            continue
        lines.append(line)
    # Collapse the runs the page's own markup produces around list items.
    text = re.sub(r"\n{2,}", "\n", "\n".join(lines)).strip()
    return text or None


def parse_detail(
    ad_id: str,
    html: str,
    *,
    url: str | None = None,
    listing_page: int | None = None,
    hint: dict | None = None,
) -> RawJobsIrelandJob:
    """Parse one detail page, falling back to the listing card where it can."""
    hint = hint or {}
    soup = BeautifulSoup(html or "", "html.parser")

    heading = soup.select_one(".job-details h3")
    title = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip() if heading else ""
    company = None
    if not title:
        title, company = split_listing_title(hint.get("JobTitle") or "")
    if not title:
        raise JobsIrelandParseError(
            f"jobsireland.ie posting {ad_id} has neither a .job-details h3 nor a "
            "listing JobTitle; the detail page markup changed."
        )

    meta = _detail_meta(soup)
    if company is None:
        company = meta.get("company")

    vacancy_type_id = hint.get("VacancyTypeId") or None
    label = VACANCY_TYPES.get(vacancy_type_id or "", (None, None))[0]

    positions = None
    match = _POSITIONS_RE.search(meta.get("positions", ""))
    if match:
        try:
            positions = int(match.group(1))
        except ValueError:
            positions = None

    hours = None
    hours_match = _HOURS_RE.search(meta.get("hours", ""))
    if hours_match:
        hours = f"{hours_match.group(1)} hours per week"

    reference = None
    ref_match = _REF_RE.search(meta.get("reference", "") or hint.get("JobReference") or "")
    if ref_match:
        reference = ref_match.group(1)

    posted = parse_iso_date(hint.get("StartDate")) or parse_long_date(meta.get("published"))
    closing = parse_iso_date(hint.get("EndDate")) or parse_long_date(meta.get("closing"))

    location = meta.get("location") or hint.get("Location") or None

    return RawJobsIrelandJob(
        source_job_id=str(ad_id),
        title=title,
        listing_title=hint.get("JobTitle") or None,
        company_name=(company or "Unknown employer").strip(),
        description=_clean_description(soup),
        location=location,
        location_reduced=reduce_location(location),
        country="Ireland",
        reference=reference,
        positions=positions,
        hours_per_week=hours,
        vacancy_type_id=vacancy_type_id,
        vacancy_type_label=label,
        posted_date=posted,
        closing_date=closing,
        company_logo_url=(hint.get("CompanyLogo") or None),
        url=url,
        listing_page=listing_page,
        raw={
            "page_bytes": len(html or ""),
            "rates_label": meta.get("rates_label"),
            "vacancy_type_meta": meta.get("vacancy_type"),
            "language": "en",
        },
    )


class JobsIrelandParser:
    """Turns JobsIreland.ie records into models."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
        hint: dict | None = None,
    ) -> RawJobsIrelandJob:
        if not html:
            raise JobsIrelandParseError(
                f"jobsireland.ie posting {job_id} has no detail HTML; the detail "
                "page was not fetched."
            )
        return parse_detail(job_id, html, url=url, listing_page=listing_page, hint=hint)

    def parse_many(self, records: list[dict]) -> tuple[list[RawJobsIrelandJob], list[str]]:
        parsed: list[RawJobsIrelandJob] = []
        issues: list[str] = []
        for record in records:
            try:
                parsed.append(
                    self.parse(
                        str(record.get("job_id") or ""),
                        record.get("html"),
                        url=record.get("url"),
                        listing_page=record.get("listing_page"),
                        hint=record.get("hint") or {},
                    )
                )
            except JobsIrelandParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} jobsireland.ie records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
