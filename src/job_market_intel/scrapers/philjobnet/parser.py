"""Parses a PhilJobNet posting's HTML into a ``RawPhilJobNetJob``.

No JSON-LD here, so this is markup extraction. The ``.portfolio-details``
block renders as a run of tokens:

    BUILDING ADMINISTRATOR
    Salary not specified
    1PRIME RETAIL CORPORATION
    Apply now
    DUMAGUETE CITY (CAPITAL), NEGROS ORIENTAL
    COLLEGE GRADUATE
    Permanent
    Job Description
    Posted on 17 October 2026
    <description>

The employer sits between the salary and "Apply now", the location between
"Apply now" and the education level, and the description after "Posted on <date>".
"""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.philjobnet.models import RawPhilJobNetJob

from .exceptions import PhilJobNetParseError

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_LONG_DATE = re.compile(
    r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{4})"
)

_SALARY_RE = re.compile(r"₱\s*([\d,]+\.\d{2})")


def _parse_date(text: str) -> date | None:
    m = _LONG_DATE.search(text or "")
    if not m:
        return None
    month = _MONTHS.get(m.group(2).lower())
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        return None


def _extract_title(soup: BeautifulSoup) -> str | None:
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        if t:
            return t.title() if t.isupper() else t
    if soup.title:
        raw = soup.title.get_text(" ", strip=True)
        # "PhilJobNet | Job Details" is not a title.
        if "|" not in raw or "Job Details" in raw:
            return None
    return None


def _extract_overview(text: str) -> dict[str, str]:
    """Cut the portfolio-details text at known labels."""
    out: dict[str, str] = {}
    labels = ("Salary", "Apply now", "Job Description", "Posted on")
    positions = sorted((text.find(lab), lab) for lab in labels if text.find(lab) != -1)
    for idx, (pos, lab) in enumerate(positions):
        end = positions[idx + 1][0] if idx + 1 < len(positions) else len(text)
        value = text[pos + len(lab) : end].strip()
        if value:
            out[lab.lower()] = value
    return out


def parse_detail(  # noqa: C901
    slug: str, html: str, url: str | None = None, listing_page: int | None = None
) -> RawPhilJobNetJob:
    """Parse one posting page."""
    soup = BeautifulSoup(html or "", "html.parser")
    title = _extract_title(soup)
    if not title:
        raise PhilJobNetParseError(
            f"PhilJobNet posting {slug} has no title in <h1>; the page was not a "
            "job detail page (an empty title means the markup changed)."
        )

    pd = soup.select_one(".portfolio-details, .container.mb-5")
    overview_text = pd.get_text(" ", strip=True) if pd else ""
    overview = _extract_overview(overview_text)

    # Employer sits between the salary and "Apply now".
    employer = "Unknown employer"
    salary_raw = overview.get("salary", "")
    apply_idx = overview_text.find("Apply now")
    if apply_idx != -1:
        before = overview_text[:apply_idx].strip()
        # before ends with "... <salary> <employer>"
        # Drop the title (first token run) and the salary token.
        tail = before
        # Remove the leading title.
        if tail.startswith(title):
            tail = tail[len(title) :].strip()
        # Remove salary token if present.
        if salary_raw and salary_raw in tail:
            tail = tail.replace(salary_raw, "", 1).strip()
        if tail:
            employer = tail

    # Location sits between "Apply now" and the education level.
    location = None
    if apply_idx != -1:
        after = overview_text[apply_idx + len("Apply now") :].strip()
        # after starts with location then education level then job type.
        # Take up to the first known education keyword.
        for marker in (
            "COLLEGE GRADUATE",
            "ELEMENTARY GRADUATE",
            "HIGH SCHOOL",
            "Educ level not specified",
            "GRADUATE",
            "Permanent",
            "Project-based",
            "Contractual",
        ):
            i = after.find(marker)
            if i != -1:
                after = after[:i].strip()
                break
        if after:
            location = after

    # Salary.
    salary_text = overview.get("salary")
    salary_min = None
    salary_max = None
    if salary_text and salary_text.lower() != "not specified":
        m = _SALARY_RE.search(salary_text)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
                salary_min = val
                salary_max = val
            except ValueError:
                pass

    # Posted date.
    posted_raw = overview.get("posted on", "")
    # overview key is 'posted on' only if 'Posted on' was a label; reconstruct.
    if not posted_raw:
        m = re.search(r"Posted on\s+(.+)$", overview_text, re.I)
        posted_raw = m.group(1).strip() if m else ""
    posted_date = _parse_date(posted_raw)

    # Description: everything after "Posted on <date>".
    desc = ""
    marker = "Posted on"
    idx = overview_text.find(marker)
    if idx != -1:
        rest = overview_text[idx:]
        # skip "Posted on 17 October 2026"
        m = re.search(r"Posted on\s+\d{1,2}\s+\w+\s+\d{4}\s*", rest, re.I)
        if m:
            desc = rest[m.end() :].strip()
    # Drop trailing boilerplate if present.
    for bp in ("Apply now",):
        if bp in desc:
            desc = desc.split(bp, 1)[-1].strip() if bp != "Apply now" else desc

    # Education level.
    education = None
    for marker in (
        "COLLEGE GRADUATE",
        "ELEMENTARY GRADUATE",
        "HIGH SCHOOL GRADUATE",
        "Educ level not specified",
        "VOCATIONAL",
    ):
        if marker in overview_text:
            education = marker
            break

    # Employment type.
    emp_type = None
    for marker in ("Permanent", "Project-based", "Contractual", "Casual", "Seasonal"):
        if marker in overview_text:
            emp_type = marker
            break

    return RawPhilJobNetJob(
        source_job_id=str(slug),
        title=title,
        company_name=employer,
        location=location,
        country="Philippines",
        description=desc or None,
        employment_type=emp_type,
        education_level=education,
        salary_text=salary_text,
        salary_min=salary_min,
        salary_max=salary_max,
        posted_date=posted_date,
        url=url,
        listing_page=listing_page,
        raw={
            "page_bytes": len(html or ""),
            "overview": overview,
            "title_tag": soup.title.get_text(" ", strip=True) if soup.title else None,
        },
    )


class PhilJobNetParser:
    """Turns a PhilJobNet detail page into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawPhilJobNetJob:
        return parse_detail(job_id, html or "", url=url, listing_page=listing_page)

    def parse_many(self, records: list[dict]) -> tuple[list[RawPhilJobNetJob], list[str]]:
        parsed: list[RawPhilJobNetJob] = []
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
            except PhilJobNetParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} PhilJobNet records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
