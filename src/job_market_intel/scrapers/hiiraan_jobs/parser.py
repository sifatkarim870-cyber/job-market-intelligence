"""Parses a Hiiraan posting's PDF text into a ``RawHiiraanJobsJob``.

The PDFs are Terms of Reference with labelled fields. Measured 2026-10-18
across four PDFs, each carrying::

    Position Title: Full-Stack Software Engineer
    Department: Information Technology
    Position Level: Level 1 Officer
    Reports To: Head of Information Technology
    Employment Type: Full-time
    Location: Mogadishu, Somalia
    Deadline for submission: 17th August 2026, 11.59 PM Mogadishu time.

The deadline date is an **ordinal** ("17th August 2026"), not ISO and not
dd/mm/yyyy, so a parser assuming either returns nothing.

No salary, no posting date, no company field. The body is the full extracted
text.
"""

from __future__ import annotations

import io
import re
from datetime import date

from loguru import logger
from pypdf import PdfReader

from job_market_intel.scrapers.hiiraan_jobs.models import RawHiiraanJobsJob

from .exceptions import HiiraanJobsParseError

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

# "17th August 2026" / "17 August 2026" / "17th August, 2026"
_ORDINAL_DATE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s*,?\s*(\d{4})")


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from a PDF using pypdf.

    Returns the empty string if extraction fails, so a single bad PDF does not
    kill a batch -- the parse step then raises ``HiiraanJobsParseError`` and the
    failure is recorded rather than raised.
    """
    if not pdf_bytes:
        return ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except Exception as exc:  # noqa: BLE001 - one bad PDF must not stop the batch
        logger.warning("hiiraan PDF extraction failed: {}", exc)
        return ""


def _field(text: str, label: str) -> str | None:
    """Read a 'Label: value' field, value on the same line."""
    m = re.search(rf"^{re.escape(label)}\s*:\s*(.+?)\s*$", text, re.I | re.M)
    if not m:
        return None
    val = m.group(1).strip()
    return val or None


def _parse_deadline(text: str) -> date | None:
    """'Deadline for submission: 17th August 2026, 11.59 PM Mogadishu time.'"""
    m = re.search(r"Deadline for submission\s*:\s*(.+?)(?:\n|$)", text, re.I)
    if not m:
        return None
    dm = _ORDINAL_DATE.search(m.group(1))
    if not dm:
        return None
    month = _MONTHS.get(dm.group(2).lower())
    if not month:
        return None
    try:
        return date(int(dm.group(3)), month, int(dm.group(1)))
    except ValueError:
        return None


def parse_detail(
    slug: str, pdf_bytes: bytes, url: str | None = None, listing_page: int | None = None
) -> RawHiiraanJobsJob:
    """Parse one PDF posting."""
    text = extract_pdf_text(pdf_bytes)
    if not text.strip():
        raise HiiraanJobsParseError(
            f"Hiiraan posting {slug} yielded no text from its PDF; the file may "
            "be scanned or corrupt."
        )

    title = _field(text, "Position Title")
    if not title:
        raise HiiraanJobsParseError(
            f"Hiiraan posting {slug} has no 'Position Title:' field in its PDF."
        )

    location_raw = _field(text, "Location")
    # "Mogadishu, Somalia" -> city "Mogadishu", country "Somalia".
    city = None
    country = "Somalia"
    if location_raw:
        parts = [p.strip() for p in location_raw.split(",")]
        if parts:
            city = parts[0] or None
        if len(parts) > 1 and parts[-1].strip():
            country = parts[-1].strip()

    return RawHiiraanJobsJob(
        source_job_id=str(slug),
        title=title,
        company_name="Unknown employer",
        department=_field(text, "Department"),
        position_level=_field(text, "Position Level"),
        reports_to=_field(text, "Reports To"),
        location=city,
        country=country,
        description=text.strip(),
        employment_type=_field(text, "Employment Type"),
        posted_date=None,
        closing_date=_parse_deadline(text),
        url=url,
        listing_page=listing_page,
        raw={
            "page_count": 0,
            "text_chars": len(text),
            "deadline_phrase": _field(text, "Deadline for submission"),
            "location_raw": location_raw,
        },
    )


class HiiraanJobsParser:
    """Turns a Hiiraan PDF into a model."""

    def parse(
        self,
        job_id: str,
        pdf_bytes: bytes | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawHiiraanJobsJob:
        return parse_detail(job_id, pdf_bytes or b"", url=url, listing_page=listing_page)

    def parse_many(self, records: list[dict]) -> tuple[list[RawHiiraanJobsJob], list[str]]:
        parsed: list[RawHiiraanJobsJob] = []
        issues: list[str] = []
        for rec in records:
            try:
                parsed.append(
                    self.parse(
                        str(rec.get("job_id") or ""),
                        rec.get("pdf_bytes"),
                        url=rec.get("url"),
                        listing_page=rec.get("listing_page"),
                    )
                )
            except HiiraanJobsParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Hiiraan records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
