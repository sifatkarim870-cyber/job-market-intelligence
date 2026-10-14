"""Parses a Job Bank Canada detail page into a ``RawJobBankJob``.

Split from the client so a network problem and a payload problem stay
distinguishable, matching the boundary every other scraper here draws.

Written against the live page rather than guessed: verified 2026-10-14 that a
posting page carries its title in ``h1``, its body in ``.job-posting-details``
(~6,100 characters), and salary/date in the first two ``dd`` elements. There is
no JSON-LD on the page, so BeautifulSoup is the only option.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.jobbank.models import RawJobBankJob

from .exceptions import JobBankParseError

#: "50.26 $/hour", "$1,200 weekly", "$5,000 per month", "$70,000 a year" and
#: "$96,557 to $128,743 annually" all occur. The connector between figure and
#: period word varies ("$", "/", "per ", "a ", or nothing), so all are allowed.
#: The first version matched only the empty case and returned None for every
_SALARY_RE = re.compile(
    r"(?P<lo>\$?\s?\d[\d,]*\.?\d*)\s*(?:-|â€“|to)?\s*"
    r"(?P<hi>\$?\s?\d[\d,]*\.?\d*)?"
    r"(?:\s*\$?\s*/?\s*(?:(?:per|a|an)\s+)?)?"
    r"(?P<per>hour|hourly|daily|day|weekly|week|monthly|month|annually|annual|year|yearly)?",
    re.I,
)
#: Canonical pay-period vocabulary, taken from the SCHEMA rather than invented:
#: salary.job_salaries.ck_job_salaries_pay_period admits ONLY
#: hourly/daily/weekly/monthly/yearly. Emitting "annually" -- the obvious word
#: for a yearly figure, and what this map originally produced -- violates the
#: constraint and costs the entire run, because the error aborts the
#: transaction that every later row shares.
_PERIOD_MAP = {
    "hour": "hourly",
    "hourly": "hourly",
    "day": "daily",
    "daily": "daily",
    "week": "weekly",
    "weekly": "weekly",
    "month": "monthly",
    "monthly": "monthly",
    "year": "yearly",
    "yearly": "yearly",
    "annual": "yearly",
    "annually": "yearly",
}
#: The occupation's MEDIAN wage, printed in the page furniture. Not this job's
#: salary -- taking it was the second bug the live run caught, and it would have
#: written a plausible-looking but wrong number into every Canadian posting.
_MEDIAN_WAGE_RE = re.compile(r"median wage", re.I)
#: Where the median-wage block sits, so a bare "50.26 $/hour" nearby is
#: recognised as occupational furniture rather than the posting's own pay.
_MEDIAN_WAGE_NEAR = re.compile(r"median wage", re.I)
#: "Title posted on Talent.com -\nSr Software Developer (Lead) - EN 178"
_TITLE_RE = re.compile(r"Title posted on [^\n]*?-\s*\n\s*(.+)", re.I)
_DEADLINE_RE = re.compile(
    r"application deadline:\s*([A-Z][a-z]{2}\s+\d{1,2}\s+\d{1,2}:\d{2}\s*[AP]M)", re.I
)
_POSTED_RE = re.compile(r"posted on\s+\n?\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", re.I)
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _parse_money(text: str) -> tuple[float | None, float | None, str | None]:
    """Extract (min, max, pay_period) from a printed salary string."""
    if not text:
        return None, None, None
    m = _SALARY_RE.search(text)
    if not m:
        return None, None, None
    try:
        lo = float(m.group("lo").replace("$", "").replace(",", "").strip())
    except ValueError:
        return None, None, None
    hi = None
    if m.group("hi"):
        try:
            hi = float(m.group("hi").replace("$", "").replace(",", "").strip())
        except ValueError:
            hi = None
    period = m.group("per")
    return lo, hi, (_PERIOD_MAP.get(period.lower()) if period else None)


class JobBankParser:
    """Turns a Job Bank posting detail page into a ``RawJobBankJob``."""

    def parse(
        self, job_id: str, html: str, search_term: str | None = None, url: str | None = None
    ) -> RawJobBankJob:
        """Parse one posting's detail page.

        Raises:
            JobBankParseError: No title could be found. A posting with no
                title is not a job posting, and silently dropping it would
                look identical to the board running out of results.
        """
        soup = BeautifulSoup(html, "html.parser")

        body = ""
        for selector in (".job-posting-details", "#job-details", "article", "main"):
            node = soup.select_one(selector)
            if node is None:
                continue
            for junk in node.select("script, style, nav, form"):
                junk.decompose()
            body = node.get_text("\n", strip=True)
            if len(body) > 200:
                break
        flat = soup.get_text("\n", strip=True)

        # --- title.
        # h1 is NOT the title. Verified live: for a posting surfaced by the
        # term "developer", h1 is literally "developer" -- the board echoes the
        # search term back. The real title is the line after "Title posted on
        # <board> -". Falling back to h1 is still better than nothing.
        title = ""
        m = _TITLE_RE.search(body)
        if m:
            title = m.group(1).strip()
        if not title:
            h1 = soup.find("h1")
            title = h1.get_text(" ", strip=True) if h1 else ""
        if not title:
            raise JobBankParseError(
                f"Job Bank posting {job_id} has no title; the page shape probably changed"
            )

        # --- salary. The dd/dt pair on this page is the OCCUPATION's median
        # wage, not this job's pay, so it is deliberately not used. The real
        # range appears in the body as "$96,557 - $128,743 annually".
        salary_text, sal_min, sal_max, period = _extract_salary(body)

        # --- employer / location: values live on the line AFTER their label.
        employer = _value_after_label(flat, ("Employer details", "Employeur"))
        location = _value_after_label(flat, ("Location:", "Location", "Lieu"))

        posted, deadline = _extract_dates(body)

        return RawJobBankJob(
            source_job_id=str(job_id),
            title=title,
            employer=employer,
            location=location,
            description=body or None,
            salary_text=salary_text,
            salary_min=sal_min,
            salary_max=sal_max,
            pay_period=period,
            posted_date=posted,
            deadline_date=deadline,
            search_term=search_term,
            url=url,
            raw={"bytes": len(html)},
        )

    def parse_many(self, records: list[dict]) -> tuple[list[RawJobBankJob], list[str]]:
        """Parse a batch, collecting failures rather than raising.

        One malformed posting must not cost a run's worth of good ones.
        """
        parsed: list[RawJobBankJob] = []
        issues: list[str] = []
        for rec in records:
            try:
                parsed.append(
                    self.parse(
                        rec.get("job_id", "?"),
                        rec.get("html", ""),
                        search_term=rec.get("search_term"),
                        url=rec.get("url"),
                    )
                )
            except JobBankParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped %s of %s Job Bank postings that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues


def _safe_date(text: str, fmt: str | None = None) -> date | None:
    """Parse a date, returning None rather than raising.

    A posting with an unreadable date is still a posting; losing it entirely
    because one field was formatted unexpectedly is the wrong trade.
    """
    text = (text or "").strip()
    if not text:
        return None
    for candidate in ([fmt] if fmt else []) + ["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"]:
        if not candidate:
            continue
        try:
            return datetime.strptime(text, candidate).date()
        except ValueError:
            continue
    m = _DATE_RE.search(text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _extract_dates(body: str) -> tuple[date | None, date | None]:
    """(posted_date, deadline_date) from a posting body.

    Split out of ``parse`` for readability; both are fiddly enough to deserve
    their own reasoning.

    The deadline needs care: Job Bank prints "Oct 23 12:00 PM ET" with no year.
    ``strptime`` without a year is deprecated and ambiguous around leap days,
    and inventing one can put a deadline in the past -- so the posting's own
    year is reused, falling back to today rather than to a confidently wrong
    value.
    """
    posted = None
    m = _POSTED_RE.search(body)
    if m:
        posted = _safe_date(m.group(1), "%B %d, %Y")

    deadline = None
    m = _DEADLINE_RE.search(body)
    if m:
        year = posted.year if posted else date.today().year
        day = re.match(r"([A-Z][a-z]{2}\s+\d{1,2})", m.group(1).strip())
        if day:
            deadline = _safe_date(f"{day.group(1)} {year}", "%b %d %Y")
    return posted, deadline


def _extract_salary(body: str) -> tuple[str | None, float | None, float | None, str | None]:
    """Find this posting's own pay, not the occupation's median wage.

    Split out of ``parse`` because the decision has two branches and the whole
    method was over the complexity limit. The distinction that matters: Job
    Bank prints a "Median wage ... 50.26 $/hour" block describing the
    OCCUPATION on every posting. Reading that as the job's salary would write a
    plausible, wrong number into every Canadian row -- which is exactly what
    the first live run did before this was separated out.
    """
    ranges = re.findall(
        r"\$?\s?\d[\d,]*\.?\d*\s*(?:-|–|to)\s*\$?\s?\d[\d,]*\.?\d*"
        r"(?:\s*\$?\s*(?:per\s+)?(?:hour|hourly|daily|weekly|monthly|"
        r"annually|annual|year|yearly))?",
        body,
    )
    if not ranges and not _MEDIAN_WAGE_NEAR.search(body or ""):
        # A single figure is a real salary only when it is not the median-wage
        # furniture this page is full of.
        single = re.search(
            r"\$?\s?\d[\d,]*\.?\d*\s*\$?\s*(?:per\s+)?"
            r"(hour|hourly|daily|weekly|monthly|annually|annual|year|yearly)",
            body,
            re.I,
        )
        if single:
            ranges = [single.group(0)]
    if not ranges:
        return None, None, None, None
    text = ranges[0].strip()
    lo, hi, period = _parse_money(text)
    return text, lo, hi, period


def _value_after_label(flat: str, labels: tuple[str, ...]) -> str | None:
    """Return the line that follows the first matching label.

    Job Bank prints labels and values on consecutive lines, so an inline
    ``label: value`` regex captures the tail of a heading instead -- an earlier
    version returned the string "s" because it matched the heading "Employers"
    with the label "employer". Matching the WHOLE line and then taking the
    next one avoids that class of mistake.
    """
    lines = [ln.strip() for ln in flat.split("\n")]
    for label in labels:
        for i, line in enumerate(lines):
            if line.lower().rstrip(":").strip() == label.rstrip(":").strip().lower():
                if i + 1 < len(lines):
                    value = lines[i + 1].strip()
                    if value and len(value) < 160:
                        return value
    return None
