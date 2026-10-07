"""Typed model for a single raw JobMaster job record.

Mirrors ``scrapers/jobinja/models.py``: the raw, source-specific
shape, one step before ``cleaning/jobmaster_cleaner.py`` maps it onto
the shared ``CleanedJob``.

Field facts confirmed live (2026-10-07) against detail pages reached
via listing cards:

* **Identity/URL** — every job lives at
  ``/jobs/checknum.asp?key={numeric id}``; the job id is the
  ``<article id="misra<ID>">`` attribute as well. Detail URLs are
  never cross-linked and there is no sitemap.
* **Detail page (server-rendered, no JSON-LD)** — beware: the
  ``<title>`` shows the *search* page context and ``og:title`` is the
  last breadcrumb *category*, so the model parses the
  ``article__jobHead`` block directly: ``<div class="CardHeader">`` is
  the job title, ``jobHead__text__addedBefore`` is a relative Hebrew
  timestamp (``פורסם לפני 16 דקות`` — "posted 16 minutes ago"), the
  company is the recruiter block (``peoplePJ--metapel_details--text__korotTitle``),
  and ``JobExtraInfo`` carries employment type (``class="jobType"``),
  location (``id="jobLocationData"``) and salary (``class="jobSalary"``,
  "לא צוין שכר" = undisclosed). The body is ``article__jobBody`` with
  ``#jobDescriptionContent`` and ``#jobRequirementsContent``.
* **Breadcrumb** — schema.org ``BreadcrumbList`` with the real
  category chain (``/jobs/q-<category>/`` links), used as tags.
* **Posting date** — no absolute timestamp anywhere on the page; the
  model resolves the relative Hebrew text against the render time and
  documents the convention.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from html import unescape

from pydantic import BaseModel, field_validator

_TAG_STRIP_RE = re.compile(r"<[^>]+>")

#: Characteristics located in whichever block carries them; order
#: independent. Manufacturer's own field set is never stable.
_TITLE_RE = re.compile(r'class="CardHeader"[^>]*>(.*?)<', re.S)
_COMPANY_RE = re.compile(r"peoplePJ--metapel_details--text__korotTitle[^>]*>(.*?)<", re.S)
_COMPANY_IMG_RE = re.compile(r'<div class="jobHead__text__img">.*?<img alt="([^"]*)"', re.S)
_POSTED_RE = re.compile(r'jobHead__text__addedBefore">\s*פורסם לפני\s*([^<]+)<')
_JOBTYPE_RE = re.compile(r'class="jobType"[^>]*>(.*?)<', re.S)
_JOBTYPE_ANCHOR_RE = re.compile(r'class="jobType"[^>]*>\s*<a[^>]*>(.*?)</a>', re.S)
_LOCATION_RE = re.compile(
    r'class="jobLocation"\s*id="jobLocationData"[^>]*>\s*<span>(.*?)</span>', re.S
)
_LOCATION_FALLBACK_RE = re.compile(r'class="jobLocation"[^>]*>\s*<a[^>]*>(.*?)</a>', re.S)
_SALARY_RE = re.compile(r'class="jobSalary"[^>]*>(.*?)</li>', re.S)
_DESC_RE = re.compile(r'<div id="jobDescriptionContent"[^>]*>(.*?)</div>', re.S)
_REQS_RE = re.compile(r'<div id="jobRequirementsContent"[^>]*>(.*?)</div>', re.S)
_BRANDCRUMB_RE = re.compile(
    r'href="(/jobs/q-[^"]+)"[^>]*>\s*<span itemprop="name">([^<]+)</span>', re.S
)


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None":
        return None
    return text


def _clean(fragment: object) -> str | None:
    """Tag-stripped, entity-decoded, whitespace-collapsed text."""
    if fragment is None:
        return None
    text = unescape(_TAG_STRIP_RE.sub(" ", str(fragment)))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _normalize_relative(text: str, *, now: datetime) -> datetime | None:
    """Resolve a relative Hebrew "פורסם לפני …" fragment against ``now``."""
    m = re.search(r"(\d+)\s*(\S+)?", text)
    if not m:
        return None
    try:
        count = int(m.group(1))
    except ValueError:
        return None
    unit = (m.group(2) or "").strip()
    if unit.startswith("דקו"):
        return now - timedelta(minutes=count)
    if unit.startswith("שע"):
        return now - timedelta(hours=count)
    if unit == "יום" or unit.startswith("ימ"):
        return now - timedelta(days=count)
    if unit.startswith("שבוע"):
        return now - timedelta(weeks=count)
    if unit.startswith("חודש"):
        return now - timedelta(days=count * 30)
    if unit.startswith("שנה"):
        return now - timedelta(days=count * 365)
    return now - timedelta(days=count)  # bare number: days


def _extract_categories(html: str) -> list[str]:
    """Breadcrumb ``/jobs/q-*`` category names, de-duplicated."""
    out: list[str] = []
    for _href, name in _BRANDCRUMB_RE.findall(html):
        name = unescape(name).strip()
        if name and name not in out:
            out.append(name)
    return out


def _extract_job_type(html: str) -> str | None:
    m = _JOBTYPE_ANCHOR_RE.search(html) or _JOBTYPE_RE.search(html)
    return _clean(m.group(1)) if m else None


class RawJobmasterJob(BaseModel):
    """A single validated JobMaster job record (detail HTML + URL)."""

    source_job_id: str
    job_title: str
    company_name: str
    company_logo_url: str | None = None
    description_html: str | None = None
    posting_date: datetime | None = None
    closing_date: datetime | None = None
    work_type_label: str | None = None
    salary_text: str | None = None
    location_text: str | None = None
    category_raws: list[str] = []
    original_url: str
    raw_payload: dict = {}

    @field_validator("source_job_id", "job_title", "company_name", mode="after")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @classmethod
    def from_page_html(cls, html: str, *, original_url: str) -> RawJobmasterJob:
        """Build from a detail page's HTML.

        Raises:
            ValueError: The page lacks the job head block (login wall or
                malformed response) — the parser turns it into a skip.
        """
        if "article__jobHead" not in html:
            raise ValueError("page has no article__jobHead (blocked, wrong page, or shape change)")

        # Scope the head-block fields to the first / second article so a
        # sidebar "more jobs of…" can't shadow the real job's header.
        head_start = html.find("article__jobHead")
        body_start = html.find("article__jobBody", head_start)
        head_html = html[head_start : body_start if body_start != -1 else None]

        title_m = _TITLE_RE.search(head_html)
        title = _clean(title_m.group(1)) if title_m else None
        if not title:
            raise ValueError("job title not found in detail page")

        company_m = _COMPANY_RE.search(head_html) or _COMPANY_RE.search(html)
        company = _clean(company_m.group(1)) if company_m else None
        if not company:
            img = _COMPANY_IMG_RE.search(head_html) or _COMPANY_IMG_RE.search(html)
            company = _text(img.group(1)) if img else None
        if not company:
            raise ValueError("company name not found in detail page")

        m = re.search(r"key=(\d+)", original_url)
        if not m:
            raise ValueError(f"cannot derive job id from url {original_url!r}")

        posted_m = _POSTED_RE.search(head_html) or _POSTED_RE.search(html)
        now = datetime.now(UTC)
        posting_date = _normalize_relative(posted_m.group(1), now=now) if posted_m else None

        description = _clean(_DESC_RE.search(html).group(1)) if _DESC_RE.search(html) else None
        requirements = _clean(_REQS_RE.search(html).group(1)) if _REQS_RE.search(html) else None
        if description and requirements:
            description_html = (
                _clean(_DESC_RE.search(html).group(1))
                + "<br><br>דרישות המשרה:<br>"
                + (_REQS_RE.search(html).group(1) if _REQS_RE.search(html) else "")
            )
        elif description:
            description_html = _DESC_RE.search(html).group(1)
        elif requirements:
            description_html = _REQS_RE.search(html).group(1)
        else:
            description_html = None

        salary_m = _SALARY_RE.search(html)
        salary_text = _clean(salary_m.group(1)) if salary_m else None

        location = None
        lm = _LOCATION_RE.search(html) or _LOCATION_FALLBACK_RE.search(html)
        if lm:
            location = _clean(lm.group(1))

        return cls(
            source_job_id=m.group(1),
            job_title=title,
            company_name=company,
            company_logo_url=None,
            description_html=description_html,
            posting_date=posting_date,
            closing_date=None,
            work_type_label=_extract_job_type(html),
            salary_text=salary_text,
            location_text=location,
            category_raws=_extract_categories(html),
            original_url=original_url,
            raw_payload={
                "title": title,
                "company": company,
                "location": location or "",
                "job_type": _extract_job_type(html) or "",
                "salary": salary_text or "",
                "posted_text": (posted_m.group(1) if posted_m else ""),
                "categories": _extract_categories(html),
            },
        )
