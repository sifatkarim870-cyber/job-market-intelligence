"""Parses an Alfred posting's JSON-LD into a ``RawAlfredJob``.

The ``JobPosting`` is at the top level, so extraction is the simple case. What
needed measuring:

* **No ``identifier``** (0 of 10 postings). The stable key is the URL slug, and
  the ``source_job_id`` is derived from it rather than from the payload.
* **No ``baseSalary``** (0 of 10). Alfred publishes no salary, so this scraper
  carries no salary handling at all rather than dead code that looks like it
  should work.
* **``validThrough`` is nullable.** ``null`` is passed through, not coerced into
  a date and not treated as an error.
* **``jobLocation`` is absent on 3 of 10**, so the location fields are all
  optional and a country-only row is a real outcome, not a failure.
* ``hiringOrganization.logo`` is a plain URL string here. Built In emits an
  ``ImageObject`` dict, so both are accepted.

``addressCountry`` is the country **name** ``"Iceland"``, where apna and
mustakbil both use an ISO code. It is passed through as the source stated it
rather than translated, because the resolver works on names in some paths and
codes in others and rewriting it would be a guess.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.alfred.models import RawAlfredJob

from .exceptions import AlfredParseError

#: Leading YYYY-MM-DD. Regex rather than fromisoformat, because Alfred has been
#: seen to emit a seven-digit fractional second elsewhere in its own payload.
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

#: Titles of general-application pages rather than vacancies. Matched on the
#: **title**, not the slug, and that distinction was measured rather than
#: assumed:
#:
#: 19 of the first 28 rows stored were general-application pages, all titled
#: "Almenn umsókn" ("general application"), and their slugs all begin
#: ``almenn-umsokn-`` (JYSK, Sky Lagoon, BAUHAUS, Sveitarfélagið Árborg, ...).
#: A slug-prefix filter looks like the obvious fix and is wrong: three *real*
#: vacancies from three different employers -- "Fullt starf hjá Brikk",
#: "Vilt þú taka þátt í að skapa einstaka up...", "Við leitum að reglulega að
#: verkafólki" -- carry that same prefix. Filtering on the slug would have
#: silently discarded three genuine jobs.
#:
#: So the title is the discriminator, and the drop therefore happens after
#: parsing rather than before it.
#: Accent-folded as well: "umsókn" folds to "umsokn", not "umsonk". Writing the
#: un-folded spelling here is a bug the tests caught -- it matched nothing.
_GENERAL_APPLICATION_TITLES = {"almenn umsokn", "general application"}


def _parse_date(value: Any) -> date | None:
    """Parse a date, tolerating null, blanks and a full ISO timestamp."""
    if not value:
        return None
    m = _DATE.match(str(value).strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _iter_nodes(payload: Any):
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            yield node
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def extract_jsonld(html: str) -> dict:
    """Pull the schema.org JobPosting out of a detail page, or ``{}``."""
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script[type='application/ld+json']"):
        try:
            payload = json.loads(tag.string or tag.get_text() or "")
        except (TypeError, ValueError):
            continue
        for node in _iter_nodes(payload):
            if node.get("@type") == "JobPosting":
                return node
    return {}


def _extract_location(ld: dict) -> tuple[str | None, str | None, str | None]:
    """jobLocation -> (label, country, city). Absent on 3 of 10 postings."""
    place = ld.get("jobLocation")
    if isinstance(place, list):
        place = next((p for p in place if isinstance(p, dict)), None)
    if not isinstance(place, dict):
        return None, None, None
    address = place.get("address")
    if not isinstance(address, dict):
        address = {}
    city = (address.get("addressLocality") or "").strip() or None
    region = (address.get("addressRegion") or "").strip() or None
    country = (address.get("addressCountry") or "").strip() or None

    parts: list[str] = []
    for part in (city, region):
        if part and part.casefold() not in {p.casefold() for p in parts}:
            parts.append(part)
    label = ", ".join(parts) if parts else country
    return (label or None), country, city


def normalise_title(title: str) -> str:
    """Lowercase, strip accents and collapse whitespace, for title matching.

    Icelandic carries ``ó``/``ó``/``é`` in these titles, so a comparison that
    does not fold accents would miss a page whenever the spelling drifted.
    """
    folded = unicodedata.normalize("NFKD", title or "")
    stripped = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().lower()


def is_general_application(title: str) -> bool:
    """Is this a general-application page rather than a vacancy?

    Takes the **title**, not the slug -- see the note on
    ``_GENERAL_APPLICATION_TITLES`` for the three real vacancies that share the
    ``almenn-umsokn-`` slug prefix.
    """
    return normalise_title(title) in _GENERAL_APPLICATION_TITLES


class AlfredParser:
    """Turns an Alfred JSON-LD block into a model."""

    def parse(
        self,
        slug: str,
        html: str | None = None,
        url: str | None = None,
    ) -> RawAlfredJob:
        """Parse one posting.

        Args:
            slug: The URL slug. Alfred publishes no ``identifier``, so this is
                the only stable key the board offers.

        Raises:
            AlfredParseError: No slug, or no title. Without a slug there is
                nothing to key the row on, and a posting with no title is not a
                posting.
        """
        slug = (slug or "").strip().strip("/")
        if not slug:
            raise AlfredParseError("no slug supplied; the payload carries no identifier")

        ld = extract_jsonld(html or "")
        title = (ld.get("title") or "").strip()
        if not title:
            raise AlfredParseError(
                f"Alfred posting {slug!r} has no title; the page carried no "
                "JobPosting title in its JSON-LD (an empty block means the "
                "markup changed)"
            )

        org = ld.get("hiringOrganization")
        if not isinstance(org, dict):
            org = {}
        logo = org.get("logo")
        if isinstance(logo, dict):
            # Built In's shape, in case this board ever changes its mind.
            logo = logo.get("url")

        location, country, city = _extract_location(ld)

        salary = ld.get("baseSalary")
        if salary is not None:
            # Not seen on any of the 10 postings measured, but if it ever
            # appears, ignoring it silently would be worse than saying so.
            logger.warning(
                "Alfred posting {!r} now carries baseSalary; this scraper has "
                "no salary handling. Re-measure before trusting the coverage "
                "numbers.",
                slug,
            )

        return RawAlfredJob(
            source_job_id=slug,
            title=title,
            company_name=(org.get("name") or "").strip() or "Unknown employer",
            company_logo_url=logo if isinstance(logo, str) and logo.strip() else None,
            employment_type=ld.get("employmentType") or None,
            location=location,
            country=country,
            city=city,
            description=ld.get("description") or None,
            posted_date=_parse_date(ld.get("datePosted")),
            closing_date=_parse_date(ld.get("validThrough")),
            direct_apply=ld.get("directApply"),
            url=url,
            slug=slug,
            raw={
                "has_identifier": "identifier" in ld,
                "has_base_salary": isinstance(salary, dict),
                "has_job_location": isinstance(ld.get("jobLocation"), (dict, list)),
                "valid_through_is_null": ld.get("validThrough") is None,
                "page_bytes": len(html or ""),
            },
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawAlfredJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawAlfredJob] = []
        issues: list[str] = []
        for rec in records:
            try:
                parsed.append(
                    self.parse(str(rec.get("slug") or ""), rec.get("html"), url=rec.get("url"))
                )
            except AlfredParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Alfred records that failed to parse", len(issues), len(records)
            )
        return parsed, issues
