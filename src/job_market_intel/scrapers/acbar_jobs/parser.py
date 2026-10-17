"""Parses an ACBAR posting's HTML into a ``RawAcbarJobsJob``.

No JSON-LD here, so this is markup extraction from a ``<dl>`` of label/value
rows. Two measured facts drive the design:

1. **The body container holds a related-jobs carousel.**
   ``.acbar-jd__body`` is 4680 characters with **six** ISO dates in it, none of
   which belong to this posting. They are removed with the
   ``.acbar-jd__related`` block before the text is taken; afterwards **zero**
   dates remain. The tell that they were foreign: the same ten dates came back
   from two *different* posting pages.

2. **``Salary`` is prose.** Measured values are ``"As Per Organization"``,
   ``"As per scale"`` and ``"Negotiable"``. The parser records the string and
   stores no amount -- the same treatment CareerJunction's ``"R Undisclosed"``
   and Jobweb Ghana's site-wide placeholder get.

The ``Education`` and ``Experience`` rows use a *different* pair shape
(``.acbar-jd__info-text`` + ``.acbar-jd__info-text-value``) from the ``<dl>``
(``.acbar-jd__info-term`` + ``.acbar-jd__info-desc``); both are read.
"""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup

from job_market_intel.scrapers.acbar_jobs.models import RawAcbarJobsJob

from .exceptions import AcbarJobsParseError

_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

#: Blocks inside the body that belong to *other* postings. Measured: the
#: related-jobs carousel is the only one, and it carries all six stray dates.
_SIDEBAR_SELECTORS = (
    ".acbar-jd__related",
    ".acbar-jd-carousel",
    "[class*='related']",
)

#: ``.acbar-jd__body`` is the measured container.
_BODY_SELECTORS = (".acbar-jd__body", ".acbar-jd__rich", "article", "main")


def _parse_date(value: str | None) -> date | None:
    """Parse ``YYYY-MM-DD``."""
    if not value:
        return None
    m = _ISO_DATE.search(str(value).strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def extract_info_rows(soup: BeautifulSoup) -> dict[str, str]:
    """Every label/value pair on the page, lower-cased labels.

    Two shapes are read because ACBAR uses two: the ``<dl>`` rows
    (``info-term``/``info-desc``) and the Education/Experience rows
    (``info-text``/``info-text-value``).
    """
    info: dict[str, str] = {}

    for row in soup.select(".acbar-jd__info-row"):
        term = row.select_one(".acbar-jd__info-term")
        desc = row.select_one(".acbar-jd__info-desc")
        if term and desc:
            key = term.get_text(" ", strip=True).strip().rstrip(":").lower()
            val = desc.get_text(" ", strip=True).strip()
            if key and val:
                info.setdefault(key, val)

    for label in soup.select(".acbar-jd__info-text"):
        # The value is the immediately following sibling of the same class.
        nxt = label.find_next_sibling(class_="acbar-jd__info-text-value")
        if nxt is None:
            continue
        key = label.get_text(" ", strip=True).strip().rstrip(":").lower()
        val = nxt.get_text(" ", strip=True).strip()
        if key and val:
            info.setdefault(key, val)

    return info


def extract_body(soup: BeautifulSoup) -> str:
    """The posting body, with other postings' blocks removed.

    The related-jobs carousel lives *inside* the body container, so leaving it
    in would splice six foreign job deadlines into this posting's description --
    and, worse, make a naive date extractor read one of them as this posting's.
    """
    for sel in _BODY_SELECTORS:
        node = soup.select_one(sel)
        if node is None:
            continue
        # decompose() destroys a tag and its descendants, so read nothing from a
        # tag afterwards and tolerate matches an earlier decompose() already
        # killed.
        for junk in list(node.select(", ".join(_SIDEBAR_SELECTORS))):
            try:
                junk.decompose()
            except AttributeError:
                continue
        text = node.get_text(" ", strip=True)
        if text:
            return text
    return ""


def extract_title(soup: BeautifulSoup) -> str | None:
    """``<h1>`` is the title; ``<title>`` is ``"ACBAR: <title>"``."""
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        if t:
            return t
    if soup.title:
        raw = soup.title.get_text(" ", strip=True)
        if raw.lower().startswith("acbar:"):
            return raw.split(":", 1)[1].strip() or None
    return None


def extract_deadline(soup: BeautifulSoup) -> date | None:
    """``.acbar-jd__deadline-label`` / ``.acbar-jd__deadline-value``."""
    value = soup.select_one(".acbar-jd__deadline-value")
    if value is not None:
        return _parse_date(value.get_text(" ", strip=True))
    return None


def parse_detail(
    job_id: str, html: str, url: str | None = None, listing_page: int | None = None
) -> RawAcbarJobsJob:
    """Parse one posting page.

    Raises:
        AcbarJobsParseError: No title.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    title = extract_title(soup)
    if not title:
        raise AcbarJobsParseError(
            f"ACBAR posting {job_id} has no title; the page carried no <h1>. An "
            "empty title means the markup changed or the id no longer resolves."
        )

    info = extract_info_rows(soup)
    body = extract_body(soup)

    return RawAcbarJobsJob(
        source_job_id=str(job_id),
        title=title,
        company_name="Unknown employer",
        salary_text=info.get("salary"),
        employment_type=info.get("type"),
        industry=info.get("category"),
        nationality=info.get("nationality"),
        gender=info.get("gender"),
        contract_duration=info.get("contract duration"),
        vacancy_number=info.get("vacancy number"),
        no_of_jobs=info.get("no of job"),
        location=info.get("location"),
        country="Afghanistan",
        description=body or None,
        posted_date=_parse_date(info.get("published")),
        closing_date=extract_deadline(soup),
        url=url,
        listing_page=listing_page,
        info=info,
        raw={
            "page_bytes": len(html or ""),
            # Proof that the sidebar removal worked: measured zero after the
            # carousel is dropped, against six before.
            "dates_left_in_body": len(_ISO_DATE.findall(body or "")),
            "title_tag": soup.title.get_text(" ", strip=True) if soup.title else None,
        },
    )


class AcbarJobsParser:
    """Turns an ACBAR detail page into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawAcbarJobsJob:
        """Parse one posting page."""
        return parse_detail(job_id, html or "", url=url, listing_page=listing_page)

    def parse_many(self, records: list[dict]) -> tuple[list[RawAcbarJobsJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawAcbarJobsJob] = []
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
            except AcbarJobsParseError as exc:
                issues.append(str(exc))
        if issues:
            logger_warning(len(issues), len(records))
        return parsed, issues


def logger_warning(dropped: int, total: int) -> None:
    """Log a batch shortfall without importing loguru at module top.

    ``parse_many`` is on the hot path and a hard import here would make the
    parser module depend on the logging stack for one line.
    """
    from loguru import logger

    logger.warning("dropped {} of {} ACBAR records that failed to parse", dropped, total)
