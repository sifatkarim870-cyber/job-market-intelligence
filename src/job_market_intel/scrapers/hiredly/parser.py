"""Turns a Hiredly ``#__NEXT_DATA__`` blob into a :class:`RawHiredlyJob`.

Everything comes from one place::

    props.pageProps.job

and never from the page's schema.org ``ld+json`` block, because the two
disagree. Measured 2026-10-18 on one posting:

===========================  ==========================  ==========================
field                        ``__NEXT_DATA__``           ``ld+json``
===========================  ==========================  ==========================
``streetAddress``            21, Jalan SS 22a/2          55, Jalan SS 1/23
``postalCode``               47400                       47300
===========================  ==========================  ==========================

The ``ld+json`` block is built from the employer's profile, so it is the
employer's registered address rather than the job's. ``__NEXT_DATA__`` is the
posting. This parser reads only the latter.

Three traps it exists to avoid
------------------------------
1. **``props.pageProps.similarJobs`` is a list of other postings.** It sits one
   level below ``job`` and every entry has a title, a company and a salary. A
   parser that searched the page for "the first thing that looks like a job"
   would happily store a neighbour.
2. **``job.salary`` is a display string** -- ``"4000 - 6000"``, or
   ``"Undisclosed"``, which is what the majority of postings say. Only
   ``structuredJobData.baseSalary.value`` is a figure, and it is absent on
   exactly the postings whose display string says "Undisclosed".
3. **The slug is the whole ``/jobs/...`` path**, including the
   ``jobs-malaysia-`` prefix. Trimming to the last segment throws away the
   company and title that the slug encodes and is not a stable key.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from loguru import logger

from job_market_intel.scrapers.hiredly.models import RawHiredlyJob

from .exceptions import HiredlyParseError

#: The one unitText measured across 30 postings. Anything else is left
#: unmapped rather than guessed at: a wrong pay_period is a CHECK-constraint
#: failure that aborts the shared transaction.
_PAY_PERIOD_BY_UNIT = {"MONTH": "monthly"}

#: "Undisclosed", "Negotiable", "Not disclosed" -- and anything else non-numeric.
_DISCLOSED = re.compile(r"\d")


def extract_next_data(html: str) -> dict[str, Any]:
    """Pull ``#__NEXT_DATA__`` out of a rendered page and JSON-parse it.

    Next.js inlines it as a plain ``<script id="__NEXT_DATA__" type="application/json">``,
    so this does not need the browser -- but the browser still has to *render*
    the page first, because the blob is only present once the app has booted.
    """
    match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if match is None:
        raise HiredlyParseError(
            "no #__NEXT_DATA__ in the rendered page. That means the app had not "
            "finished booting -- on this site it is also what a rate-limited "
            "response looks like, so it is treated as a fetch failure upstream."
        )
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise HiredlyParseError(f"#__NEXT_DATA__ is not valid JSON: {exc}") from exc


def extract_job_node(blob: dict[str, Any], slug: str) -> dict[str, Any]:
    """``props.pageProps.job``, or raise. Never ``similarJobs``."""
    props = ((blob or {}).get("props") or {}).get("pageProps") or {}
    job = props.get("job")
    if not isinstance(job, dict) or not job:
        raise HiredlyParseError(
            f"__NEXT_DATA__.props.pageProps.job is missing for {slug}. Note the "
            "page also carries props.pageProps.similarJobs -- a list of OTHER "
            "postings -- which is deliberately never used as a fallback."
        )
    return job


def _slug_from_href(href: str | None) -> str | None:
    """``/jobs/jobs-malaysia-acme-job-plumber-123`` -> the slug after ``/jobs/``."""
    if not href or "/jobs/" not in href:
        return None
    slug = href.split("/jobs/", 1)[1].strip("/")
    slug = slug.split("?", 1)[0].split("#", 1)[0].strip("/")
    if not slug or len(slug) < 12 or "/" in slug:
        return None
    if not slug.startswith("jobs-malaysia-"):
        return None
    return slug


def parse_salary(job: dict[str, Any]) -> tuple[int | None, int | None, str | None]:
    """``(min, max, currency)`` from ``structuredJobData.baseSalary`` only.

    The display string ``job["salary"]`` is *not* parsed. It reads
    ``"Undisclosed"`` on most postings, and a regex that scraped digits out of
    it would turn the word "Undisclosed" into a salary of nothing while
    looking like it had worked.
    """
    base = ((job.get("structuredJobData") or {}).get("baseSalary")) or {}
    value = base.get("value") or {}
    currency = base.get("currency")

    def _int(raw: Any) -> int | None:
        if isinstance(raw, bool) or raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    low = _int(value.get("minValue"))
    high = _int(value.get("maxValue"))
    if low is None and high is None:
        shown = job.get("salary")
        if isinstance(shown, str) and _DISCLOSED.search(shown):
            logger.warning(
                "hiredly posting {} shows a salary string {!r} but no "
                "baseSalary.value; leaving the salary unrecorded rather than "
                "parsing the display text",
                (job.get("title") or "")[:50],
                shown[:30],
            )
        return None, None, currency
    if low is None:
        low = high
    if high is None:
        high = low
    return low, high, currency


def _join_location(job: dict[str, Any]) -> str | None:
    """``location`` + ``stateRegion``. Both are published; neither is invented."""
    parts = [
        str(job.get(k)).strip()
        for k in ("location", "stateRegion")
        if job.get(k) and str(job.get(k)).strip()
    ]
    return ", ".join(parts) if parts else None


def _names(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            name = item.get("name") or item.get("title")
        else:
            name = item
        if name and str(name).strip():
            out.append(str(name).strip())
    return out


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        logger.debug("hiredly: unparsable date {!r}", value)
        return None


def parse_detail(
    slug: str,
    html: str,
    *,
    url: str | None = None,
    listing_page: int | None = None,
) -> RawHiredlyJob:
    """Parse one rendered detail page."""
    job = extract_job_node(extract_next_data(html), slug)

    title = str(job.get("title") or "").strip()
    if not title:
        raise HiredlyParseError(f"hiredly posting {slug} has an empty title")

    structured = job.get("structuredJobData") or {}
    company = job.get("company") or {}
    logo = company.get("logo") or company.get("logoUrl") or company.get("picture")
    low, high, currency = parse_salary(job)

    description = structured.get("description")
    if description and not str(description).strip():
        description = None

    return RawHiredlyJob(
        source_job_id=slug,
        title=title,
        company_name=str(company.get("name") or "").strip() or "Unknown employer",
        company_industry=str(company.get("industry") or "").strip() or None,
        company_logo_url=str(logo) if logo else None,
        location=_join_location(job),
        country="Malaysia",
        description=description,
        requirements=str(job.get("requirements") or "").strip() or None,
        employment_type=str(structured.get("employmentType") or "").strip() or None,
        job_category=", ".join(_names(job.get("tracks"))) or None,
        skills=_names(job.get("skills")),
        min_years_experience=job.get("minYearsExperience"),
        max_years_experience=job.get("maxYearsExperience"),
        salary_min=low,
        salary_max=high,
        salary_currency=str(currency) if currency else "MYR",
        salary_unit_text=str((structured.get("baseSalary") or {}).get("value", {}).get("unitText"))
        or None,
        posted_date=_as_date(structured.get("datePosted")),
        closing_date=_as_date(structured.get("validThrough")),
        url=url,
        listing_page=listing_page,
        raw={
            "page_bytes": len(html or ""),
            "salary_display": job.get("salary"),
            "location_raw": job.get("location"),
            "state_region": job.get("stateRegion"),
            "company_register_name": company.get("registerName"),
            "language": "en",
        },
    )


class HiredlyParser:
    """Turns Hiredly records into models."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawHiredlyJob:
        if not html:
            raise HiredlyParseError(
                f"hiredly posting {job_id} has no rendered HTML; the detail page "
                "was not fetched. Discovery alone is not stored, because a "
                "posting with no description is not worth a row."
            )
        return parse_detail(job_id, html, url=url, listing_page=listing_page)

    def parse_many(self, records: list[dict]) -> tuple[list[RawHiredlyJob], list[str]]:
        parsed: list[RawHiredlyJob] = []
        issues: list[str] = []
        for record in records:
            try:
                parsed.append(
                    self.parse(
                        str(record.get("job_id") or ""),
                        record.get("html"),
                        url=record.get("url"),
                        listing_page=record.get("listing_page"),
                    )
                )
            except HiredlyParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Hiredly records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
