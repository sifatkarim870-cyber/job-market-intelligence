"""Turns a Forasna response into a :class:`RawForasnaJob`.

Both page shapes were read off live responses on 2026-10-19.

Traps this parser exists to avoid
--------------------------------
1. **The nominal all-jobs route has no postings on it.** ``/a/وظائف-مصر``
   returns HTTP 200 and 281 KB with zero ``/job/p/`` links. The site's search
   page ``/وظائف-خالية`` is the listing that works, and it is what the
   client requests. A parser fed the wrong page would simply find nothing.

2. **The id is the trailing number of the URL slug**, and the JSON-LD
   ``identifier.value`` agrees with it. The slug is Arabic and URL-encoded, so
   the number is taken from the *raw* href, not from a decoded string where a
   trailing digit could belong to a word.

3. **The currency is per posting.** One sampled posting on an Egyptian board
   declares **USD**. It is read from the record, never assumed to be EGP.

4. **``addressRegion`` can be a governorate of another country** -- one
   sampled posting says "أبها", which is Abha in Saudi Arabia. The country is
   taken from ``addressCountry``, so a Saudi posting is not filed under Egypt.

5. **The description is missing on 27% of postings.** The employer left the
   body empty. The page then shows only the structured requirements block,
   which is not a description and is not stored as one.

6. **A posting's slug is not a title.** The slug carries the title, the
   company, the country, the city and the id, all concatenated; the title
   comes from the JSON-LD, and the slug is only used for the id.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.forasna.models import (
    EMPLOYMENT_TYPES,
    UNIT_TO_PAY_PERIOD,
    RawForasnaJob,
)

from .exceptions import ForasnaParseError

#: ``/job/p/<slug>`` -- the id is the trailing number of the slug.
#:
#: The character class excludes ``<``, ``>`` and the quote characters as well
#: as the path separators, because a malformed href must not swallow the
#: following anchor. Found by accident: a fixture with an unclosed
#: ``href="/job/p/<slug>`` produced a match of
#: ``<slug>>read more</a>\n<a href="/job/p/<next-slug>`` -- one "posting" that
#: was three. On a live page an over-permissive slug pattern silently eats
#: postings, so the class is tight on purpose.
_JOB_PATH_RE = re.compile(r"/job/p/([^/?#<>\"']+)")
_TRAILING_ID_RE = re.compile(r"(\d+)$")
#: A same-countryside href may carry a query string instead.
_ID_QUERY_RE = re.compile(r"[?&]id=(\d+)")

#: The heading above the ad body, Arabic for "job details".
_DETAILS_HEADING = "تفاصيل"
#: The heading above the structured requirements block, "the job's requirements".
_REQUIREMENTS_HEADING = "متطلبات"


def slug_id(slug: str) -> str | None:
    """The trailing number of a job slug: ``...-444468`` -> ``"444468"``."""
    match = _TRAILING_ID_RE.search(slug or "")
    return match.group(1) if match else None


def parse_listing(html: str) -> list[tuple[str, str]]:
    """``[(slug, id)]`` for the postings on a listing page.

    Only the detail paths count. The pages carry hundreds of other anchors --
    categories, cities, companies, "see all jobs" links -- and several of
    those carry numbers in their text, so the shape of the path is the
    discriminator rather than the presence of a digit.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"] or ""
        match = _JOB_PATH_RE.search(href)
        if match is None:
            continue
        slug = match.group(1)
        if slug in seen:
            continue
        seen.add(slug)
        job_id = slug_id(slug)
        if job_id is None:
            # A slug without a trailing number: fall back to an id in the
            # query string, and give up if there is none.
            qmatch = _ID_QUERY_RE.search(href)
            if qmatch is None:
                continue
            job_id = qmatch.group(1)
        out.append((slug, job_id))
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
            # Some pages put several objects in one block.
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    return item
    return None


def _parse_iso(value: Any) -> date | None:
    """``2026-10-19T20:27:15+03:00`` -> ``date(2026, 10, 19)``."""
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


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"[ \t]+", " ", value).strip()
    return text or None


def _page_description(soup: BeautifulSoup) -> str | None:
    """The ad body from the page, for the 27% of postings with no JSON-LD one.

    The page puts the body in the block whose heading is "تفاصيل الوظيفة"
    ("job details"). The requirements block -- "متطلبات الوظيفة" -- is a
    separate section of structured fields and is NOT a description, so it is
    excluded.

    The heading is walked up to the ancestor that actually has siblings: its
    immediate parent is a single-child title wrapper, so stopping there finds
    nothing at all.
    """
    for heading in soup.find_all(["h2", "h3", "h4"]):
        text = heading.get_text(" ", strip=True)
        if _DETAILS_HEADING not in text or _REQUIREMENTS_HEADING in text:
            continue
        block = heading.parent
        while block is not None and len(block.find_all(recursive=False)) < 2:
            block = block.parent
        if block is None:
            continue
        for sibling in block.find_all(recursive=False):
            if sibling is heading or sibling.find(heading) is not None:
                continue
            # The requirements block is a sibling of the body and is long
            # enough to pass the length threshold, so it is excluded by its
            # own heading rather than by length.
            if _REQUIREMENTS_HEADING in sibling.get_text(" ", strip=True)[:60]:
                continue
            body = re.sub(r"\s+", " ", sibling.get_text(" ", strip=True)).strip()
            if len(body) >= 40:
                return body
    return None


def _parse_salary(data: dict) -> tuple[int | None, int | None, str | None, str | None]:
    """``(min, max, currency, pay_period)`` from ``baseSalary``.

    The currency is the record's own -- one sampled posting on this Egyptian
    board declares **USD** and one declares **SAR** -- so it is never
    assumed to be EGP.
    """
    salary = data.get("baseSalary")
    if not isinstance(salary, dict):
        return None, None, None, None
    currency = _clean_text(salary.get("currency"))
    value = salary.get("value") or {}
    if not isinstance(value, dict):
        value = {}
    pay_period = UNIT_TO_PAY_PERIOD.get(str(value.get("unitText") or "").upper())
    return (
        _as_int(value.get("minValue")),
        _as_int(value.get("maxValue")),
        currency,
        pay_period,
    )


def _parse_address(data: dict) -> tuple[str | None, str | None, str | None]:
    """``(locality, region, country)`` from ``jobLocation.address``.

    The country comes from ``addressCountry`` and NOT from the region: one
    sampled posting's region is "أبها", which is Abha, in **Saudi Arabia**,
    and 5 of 280 postings are SA rather than EG.
    """
    location = data.get("jobLocation") or {}
    if not isinstance(location, dict):
        location = {}
    address = location.get("address") or {}
    if not isinstance(address, dict):
        address = {}
    return (
        _clean_text(address.get("addressLocality")),
        _clean_text(address.get("addressRegion")),
        _clean_text(address.get("addressCountry")),
    )


def parse_detail(
    slug: str,
    html: str,
    *,
    url: str | None = None,
    listing_page: int | None = None,
    job_id: str | None = None,
) -> RawForasnaJob:
    """Parse one Forasna detail page."""
    soup = BeautifulSoup(html or "", "html.parser")
    data = _json_ld_jobposting(soup)
    if data is None:
        raise ForasnaParseError(
            f"forasna posting {slug[:40]} has no schema.org JobPosting block; the "
            "page markup changed, or this is not a job detail page."
        )

    title = _clean_text(data.get("title"))
    if not title:
        raise ForasnaParseError(
            f"forasna posting {slug[:40]} has a JobPosting block with no title."
        )

    identifier = data.get("identifier")
    if isinstance(identifier, dict):
        identifier = identifier.get("value")
    resolved_id = str(identifier) if identifier else (job_id or slug_id(slug) or "")
    if not resolved_id:
        raise ForasnaParseError(
            f"forasna posting {slug[:40]} has no id: neither the JobPosting "
            "identifier nor a trailing number on the slug."
        )

    org = data.get("hiringOrganization") or {}
    if not isinstance(org, dict):
        org = {}
    company = _clean_text(org.get("name"))

    locality, region, country = _parse_address(data)
    salary_min, salary_max, salary_currency, pay_period = _parse_salary(data)

    employment_type = _clean_text(data.get("employmentType"))
    employment_code = None
    if employment_type:
        employment_code = EMPLOYMENT_TYPES.get(employment_type.upper())
        if employment_code is None and employment_type.upper() not in EMPLOYMENT_TYPES:
            logger.warning(
                "Unrecognized Forasna employmentType {!r} -- left None.", employment_type
            )

    description = _clean_text(data.get("description")) or _page_description(soup)

    return RawForasnaJob(
        source_job_id=resolved_id,
        title=title,
        company_name=company or "Unknown employer",
        description=description,
        location=_join_location(locality, region),
        locality=locality,
        region=region,
        country=country,
        employment_type=employment_type,
        employment_type_code=employment_code,
        posted_date=_parse_iso(data.get("datePosted")),
        closing_date=_parse_iso(data.get("validThrough")),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=salary_currency,
        pay_period=pay_period,
        url=url,
        listing_page=listing_page,
        raw={
            "page_bytes": len(html or ""),
            "language": "ar",
            "company_url": org.get("sameAs") if isinstance(org, dict) else None,
            "has_json_ld_description": bool(_clean_text(data.get("description"))),
            "applicant_location_requirements": bool(data.get("applicantLocationRequirements")),
        },
    )


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _join_location(locality: str | None, region: str | None) -> str | None:
    """``"locality, region"`` -- the shape the resolver can act on.

    The resolver splits on ``;`` and its comma fallback is built for a
    two-part "City, ST", so the two pieces are joined with a comma. A
    single piece is returned alone.
    """
    if locality and region and locality != region:
        return f"{locality}, {region}"
    return locality or region


class ForasnaParser:
    """Turns Forasna records into models."""

    def parse(
        self,
        slug: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
        job_id: str | None = None,
    ) -> RawForasnaJob:
        if not html:
            raise ForasnaParseError(
                f"forasna posting {slug[:40]} has no detail HTML; the detail page was not fetched."
            )
        return parse_detail(slug, html, url=url, listing_page=listing_page, job_id=job_id)

    def parse_many(self, records: list[dict]) -> tuple[list[RawForasnaJob], list[str]]:
        parsed: list[RawForasnaJob] = []
        issues: list[str] = []
        for record in records:
            try:
                parsed.append(
                    self.parse(
                        str(record.get("slug") or ""),
                        record.get("html"),
                        url=record.get("url"),
                        listing_page=record.get("listing_page"),
                        job_id=record.get("job_id"),
                    )
                )
            except ForasnaParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} forasna records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
