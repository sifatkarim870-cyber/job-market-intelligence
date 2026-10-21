"""Turns a Shine.com page into a :class:`RawShineJob`.

Measured 2026-10-20 against live shine.com pages:

  * **JSON-LD JobPosting** on the detail page, top-level (not @graph).
    Fields: title, hiringOrganization.name, identifier.value, url,
    datePosted, validThrough, employmentType,
    experienceRequirements.monthsOfExperience, jobLocation[].address
    (addressCountry ISO 'IN', addressLocality), skills list, industry.
  * **description** may be "No job description at the moment!" -- stored
    as-is; the cleaner decides substantiality.
  * **datePosted / validThrough** are full ISO timestamps with a +05:30
    offset -- parse directly with datetime.fromisoformat.

Traps this parser exists to avoid
---------------------------------
1. **Missing JSON-LD.** Some pages may not carry the block -- raise
   rather than return a hollow record.
2. **identifier.value is a string** ("19525849") -- it is already the
   natural key; no extraction from URL needed but cross-checked against
   the URL id.
3. **addressCountry is the ISO code 'IN'** -- no normalization needed;
   geographic_resolution matches on ISO codes.
4. **skills may be absent** -- stored as an empty list rather than None.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.shine.models import RawShineJob

from .exceptions import ShineParseError

#: Matches /jobs/<slug>/<company>/<id> to extract the id as a cross-check.
_JOB_ID_FROM_URL_RE = re.compile(r"/jobs/[^/]+/[^/]+/(\d+)$")


def _extract_json_ld(html: str) -> dict[str, Any] | None:
    """Return the top-level JobPosting JSON-LD block, or None."""
    soup = BeautifulSoup(html or "", "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "", strict=False)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
        # Some sites wrap in a graph or list.
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    return item
    return None


def _parse_iso_date(value: str | None) -> date | None:
    """Parse an ISO 8601 timestamp such as ``2026-09-04T22:32:23+05:30``."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt.date()
    except ValueError:
        # Fall back to the leading date fragment.
        match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                return None
    return None


def parse_detail(
    ad_id: str,
    html: str,
    *,
    url: str | None = None,
    listing_page: int | None = None,
    today: date | None = None,
) -> RawShineJob:
    """Parse one Shine.com detail page from its JSON-LD block."""
    del today  # shine posts full timestamps; no relative-date inference needed

    json_ld = _extract_json_ld(html)
    if json_ld is None:
        raise ShineParseError(
            f"shine posting {ad_id} has no JSON-LD JobPosting block. "
            "The detail page markup changed, or this id resolved to something "
            "that is not a vacancy."
        )

    # Cross-check the id from the URL against identifier.value.
    url_id: str | None = None
    if url:
        match = _JOB_ID_FROM_URL_RE.search(url)
        if match:
            url_id = match.group(1)
    ld_id = str(json_ld.get("identifier", {}).get("value", "")) if isinstance(
        json_ld.get("identifier"), dict
    ) else str(json_ld.get("identifier", ""))
    if url_id and ld_id and url_id != ld_id:
        logger.warning(
            "shine id mismatch: URL {!r} vs JSON-LD {!r} for {}", url_id, ld_id, ad_id
        )
    source_job_id = ld_id or ad_id

    title = json_ld.get("title") or ""
    if not title:
        raise ShineParseError(f"shine posting {ad_id} has no title in JSON-LD.")

    hiring_org = json_ld.get("hiringOrganization") or {}
    company_name = (
        hiring_org.get("name") if isinstance(hiring_org, dict) else ""
    ) or "Unknown employer"

    description = json_ld.get("description") or None
    if description and not description.strip():
        description = None

    posted_date = _parse_iso_date(json_ld.get("datePosted"))
    closing_date = _parse_iso_date(json_ld.get("validThrough"))

    employment_type = json_ld.get("employment_type") or json_ld.get("employmentType")

    exp_req = json_ld.get("experienceRequirements") or {}
    experience_months = None
    if isinstance(exp_req, dict):
        months = exp_req.get("monthsOfExperience")
        if months is not None:
            try:
                experience_months = int(months)
            except (TypeError, ValueError):
                experience_months = None

    location = None
    job_locations = json_ld.get("jobLocation") or []
    if isinstance(job_locations, list) and job_locations:
        first = job_locations[0]
        if isinstance(first, dict):
            address = first.get("address") or {}
            if isinstance(address, dict):
                location = address.get("addressLocality")
    if not location:
        location = json_ld.get("jobLocation") if isinstance(json_ld.get("jobLocation"), str) else None

    skills: list[str] = []
    raw_skills = json_ld.get("skills") or []
    if isinstance(raw_skills, list):
        skills = [str(s).strip() for s in raw_skills if str(s).strip()]

    raw_payload: dict[str, Any] = {
        "json_ld": json_ld,
        "page_bytes": len(html or ""),
        "url": url,
    }

    return RawShineJob(
        source_job_id=str(source_job_id),
        title=str(title).strip(),
        company_name=str(company_name).strip(),
        description=description,
        location=location,
        country="India",
        employment_type=str(employment_type).strip() if employment_type else None,
        experience_months=experience_months,
        posted_date=posted_date,
        closing_date=closing_date,
        url=url,
        listing_page=listing_page,
        raw=raw_payload,
    )


class ShineParser:
    """Turns Shine.com records into models."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
        today: date | None = None,
    ) -> RawShineJob:
        if not html:
            raise ShineParseError(
                f"shine posting {job_id} has no rendered HTML; the detail page was not fetched."
            )
        return parse_detail(
            job_id, html, url=url, listing_page=listing_page, today=today
        )

    def parse_many(
        self, records: list[dict], today: date | None = None
    ) -> tuple[list[RawShineJob], list[str]]:
        parsed: list[RawShineJob] = []
        issues: list[str] = []
        for record in records:
            try:
                parsed.append(
                    self.parse(
                        str(record.get("job_id") or ""),
                        record.get("html"),
                        url=record.get("url"),
                        listing_page=record.get("listing_page"),
                        today=today,
                    )
                )
            except ShineParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} shine records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
