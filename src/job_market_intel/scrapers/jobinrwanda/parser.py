"""Parses a Job in Rwanda posting's HTML into a ``RawJobInRwandaJob``.

There is no JSON-LD here, so this is markup extraction rather than structured
parsing. Two measured facts drive the design:

1. **The title is in ``<title>``, formatted ``"<Job Title> | Job in Rwanda"``.**
   Split on the last ``" | "`` and take the left side. Verified against a long
   title that itself contains no bar, and one that does not contain the site
   suffix at all.

2. **There is no posting date.** Four of six inspected pages carry no date, and
   the two that do carry one only ever carry a *deadline*, in prose. So the date
   regex is anchored to deadline wording, and ``posted_date`` is left ``None``
   even when a date is found. Writing a deadline into ``posting_date`` would
   assert a recency the site never claimed, and every downstream "how fresh is
   this corpus" question would be answered with a lie.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.scrapers.jobinrwanda.models import RawJobInRwandaJob

from .exceptions import JobInRwandaParseError

#: ``<title>`` suffix the site appends to every posting.
_TITLE_SUFFIX = re.compile(r"\s*\|\s*Job in Rwanda\s*$", re.I)

#: A long-form date, e.g. "19 October 2026".
_LONG_DATE = (
    r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{4})"
)

#: A date that the page explicitly calls a **deadline**. Only these are read,
#: and they are recorded as ``closing_date``.
#:
#: Measured phrases that must match::
#:     "The deadline for submission of applications is 19 October 2026 at 5:00 PM"
#:     "Application deadline Sunday 25 October 2026 - places filled on a rolling basis"
#:     "Application Deadline 28 November 2026 ."
#:
#: The window is deliberately short (120 characters) so the word has to be
#: near the date. Without that, any date anywhere near the word "deadline"
#: would qualify.
#:
#: "closing date" and "closes on" are accepted alongside "deadline" because they
#: name the same thing, and a board that used them would otherwise lose every
#: date it publishes.
_DEADLINE_DATE = re.compile(
    r"(?:deadline|closing\s+date|closes?\s+on)[^.]{0,120}?" + _LONG_DATE, re.I | re.S
)

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

#: Site boilerplate that is not part of the posting. Measured verbatim.
_BOILERPLATE = re.compile(
    r"Click on the APPLY button to send your application documents:.*", re.I | re.S
)

#: Body container. Measured across three pages; ``.node__content`` is stable and
#: is a descendant of ``.node--type-job``.
_BODY_SELECTORS = (".node__content", ".node--type-job", "main", "#content")


def _extract_title(soup: BeautifulSoup) -> str | None:
    """``<title>`` minus the site's ``"| Job in Rwanda"`` suffix."""
    raw = soup.title.get_text(" ", strip=True) if soup.title else ""
    if not raw:
        return None
    stripped = _TITLE_SUFFIX.sub("", raw).strip()
    # A page whose <title> is only the suffix yields nothing useful.
    return stripped or None


def _extract_body(soup: BeautifulSoup) -> str:
    """The posting body, with site boilerplate removed."""
    for sel in _BODY_SELECTORS:
        el = soup.select_one(sel)
        if el is None:
            continue
        # .node__content often *contains* .field--name-body; drop it so the
        # "Click on the APPLY button..." instructions do not become the
        # description of every single posting.
        for junk in el.select(".field--name-body, .field--name-field-attachment"):
            junk.decompose()
        text = el.get_text(" ", strip=True)
        if text:
            cleaned = _BOILERPLATE.sub("", text).strip()
            if cleaned:
                return cleaned
    return ""


def _extract_deadline(text: str) -> tuple[date | None, str | None]:
    """A deadline-shaped date -> (date, the phrase it came from).

    Returns ``(None, None)`` when the page states no deadline. The phrase is
    returned so the raw evidence survives into ``raw_payload`` and a reader can
    check the extraction rather than trust it.
    """
    m = _DEADLINE_DATE.search(text or "")
    if not m:
        return None, None
    month = _MONTHS.get(m.group(2).lower())
    if not month:
        return None, None
    try:
        return date(int(m.group(3)), month, int(m.group(1))), m.group(0).strip()
    except ValueError:
        return None, None


def parse_detail(
    slug: str, html: str, url: str | None = None, listing_page: int | None = None
) -> RawJobInRwandaJob:
    """Parse one posting page.

    Raises:
        JobInRwandaParseError: No title. The title is the only structural field
            this board offers, so a page without one is not a posting.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    title = _extract_title(soup)
    if not title:
        raise JobInRwandaParseError(
            f"Job in Rwanda posting {slug} has no title in <title>; the page "
            "returned was not a job detail page (an empty title here means the "
            "markup changed or the slug no longer resolves)"
        )

    body = _extract_body(soup)
    closing, phrase = _extract_deadline(body or "")

    # Locations are named in the prose ("Head Office", "Kigali") but there is no
    # location field, so nothing is asserted. Rwanda is supplied by
    # SOURCE_HOME_COUNTRY as the fallback.
    return RawJobInRwandaJob(
        source_job_id=str(slug),
        title=title,
        company_name="Unknown employer",
        location=None,
        country=None,
        description=body or None,
        # Deliberately None: the site publishes no posting date. See the module
        # docstring -- every date here is a deadline, not a publication date.
        posted_date=None,
        closing_date=closing,
        url=url,
        listing_page=listing_page,
        raw={
            "page_bytes": len(html or ""),
            "title_tag": soup.title.get_text(" ", strip=True) if soup.title else None,
            "deadline_phrase": phrase,
            "body_chars": len(body),
        },
    )


class JobInRwandaParser:
    """Turns a Job in Rwanda detail page into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawJobInRwandaJob:
        """Parse one posting page."""
        return parse_detail(job_id, html or "", url=url, listing_page=listing_page)

    def parse_many(self, records: list[dict]) -> tuple[list[RawJobInRwandaJob], list[str]]:
        """Parse a batch, collecting failures rather than raising."""
        parsed: list[RawJobInRwandaJob] = []
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
            except JobInRwandaParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Job in Rwanda records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues


def summarize(raw: RawJobInRwandaJob) -> dict[str, Any]:
    """A small dict for logs. Not part of the model."""
    return {
        "id": raw.source_job_id,
        "title": raw.title[:60],
        "closing_date": raw.closing_date.isoformat() if raw.closing_date else None,
        "body_chars": raw.raw.get("body_chars", 0),
    }
