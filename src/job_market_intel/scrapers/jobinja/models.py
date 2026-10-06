"""Typed model for a single raw Jobinja job record.

Mirrors the role ``scrapers/glints/models.py`` plays for Glints: the
raw, source-specific shape, one step before
``cleaning/jobinja_cleaner.py`` maps it onto the shared ``CleanedJob``.

Field facts confirmed live (2026-10-07) against job pages discovered
via the listing (``https://jobinja.ir/jobs?page=N``):

* **Detail URL** — ``/companies/{company-slug}/jobs/{code}/{Persian-
  slug}``; the 4-char ``code`` is per-job (recovered under one company:
  11 URLs → distinct records), cards may append ``?_ref=…&_t=…``
  tracking params which the client strips.
* **JSON-LD ``JobPosting``** — every sampled page (6/6) embeds exactly
  one ``<script type="application/ld+json">`` block with:
  ``identifier`` (``PropertyValue`` — ``value`` is a numeric job id,
  job-scoped: 5 jobs of one company → 5 distinct values), ``title``
  (Persian), ``description`` (HTML, RTL lists), ``datePosted``
  (``YYYY-MM-DD``), ``validThrough`` (0/10 sampled — rare, so
  ``closing_date`` is mostly honest absence), ``employmentType``
  (``FULL_TIME`` observed), ``baseSalary`` (``MonetaryAmount`` —
  ``currency: "IRT"``, scalar ``value`` e.g. 45000000, ``unitText:
  "MONTH"``, 10/10 sampled), ``hiringOrganization`` (``name`` +
  ``logo`` on the ``thumb2.jobinjacdn.com`` CDN), ``jobLocation``
  (``addressCountry`` IR; no city — city lives in the HTML section),
  ``jobLocationType`` (``TELECOMMUTE`` on remote posts).
* **HTML metadata sections** — a repeating ``<h4>heading</h4><div
  class="tags"><span class="black">chip</span>…`` structure supplies
  what the JSON-LD lacks: ``موقعیت مکانی`` (location, e.g. "تهران ،
  تهران" = Tehran, Tehran), ``مهارت‌های مورد نیاز`` (skill chips),
  ``دسته‌بندی شغلی`` (category chip), ``حقوق`` (salary text — "از
  ۴۵,۰۰۰,۰۰۰ تومان" = "from 45,000,000 toman" in Persian numerals, or
  "توافقی" = negotiable). The salary section is the *disclosure truth*:
  negotiable jobs still carry a numeric JSON-LD ``baseSalary`` (observed
  value 5000000 beside "توافقی"), so the cleaner withholds when the
  section says negotiate and only falls back to the JSON-LD figure when
  the section is missing or unparseable.

No public JSON API (``/api/v10/*`` is auth-only; bundle-mined routes
are resume/notification endpoints) and no sitemaps — the model's input
is the raw detail HTML, which the parser hands over as
``{"url": …, "html": …}``.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html import unescape

from pydantic import BaseModel, field_validator

_TAG_STRIP_RE = re.compile(r"<[^>]+>")

#: ``<h4>…</h4>`` followed by the flat ``<div class="tags">…</div>``
#: chips block. The heading group is tempered against a nested ``<h4``
#: #: so a section whose real body is *not* a tags-div (e.g. the
#: description block) can't backtrack into a mega-heading that swallows
#: the following sections — observed live (2026-10-07): plain ``.*?``
#: let ``شرح موقعیت شغلی``'s heading run on to the next ``</h4>`` and
#: captured the language chips as "skills". The div accepts extra
#: classes around ``tags`` but still requires the token.
_SECTION_RE = re.compile(
    r'<h4[^>]*>((?:(?!<h4).)*)</h4>\s*'
    r'<div[^>]*class="[^"]*\btags\b[^"]*"[^>]*>(.*?)</div>',
    re.S,
)
_SPAN_RE = re.compile(r"<span[^>]*>(.*?)</span>", re.S)
_LDJSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S
)


def _parse_iso_date(value: object) -> datetime | None:
    """Parse Jobinja's JSON-LD dates (``datePosted``/``validThrough``).

    Observed as date-only ISO (``2026-10-06``); full ISO-8601 accepted
    too. Naive values are assumed UTC. Unparseable values become
    ``None`` — honest absence rather than a crash; the batch validator
    flags rows missing a posting date.
    """
    if value is None or value == "" or value == "None":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _text_or_none(value: object) -> str | None:
    """Trimmed non-empty string, or None — tolerates ``"None"``/blank."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None":
        return None
    return text


def _plain_markup(fragment: str) -> str:
    """Tag-stripped, entity-decoded, whitespace-collapsed text."""
    text = unescape(_TAG_STRIP_RE.sub(" ", fragment))
    return re.sub(r"\s+", " ", text).strip()


def _extract_job_posting(html: str) -> dict:
    """The page's JSON-LD ``JobPosting`` object.

    Raises:
        ValueError: no usable ``JobPosting`` block (page without
            structured data or a shape change) — the parser skips such
            records instead of crashing the run.
    """
    for block in _LDJSON_RE.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    raise ValueError("page embeds no JSON-LD JobPosting block")


def _extract_tag_sections(html: str) -> dict[str, list[str]]:
    """All ``<h4>heading</h4><div class="tags">`` sections, in page order.

    Returns:
        Mapping heading text → cleaned chip texts (span-level when the
        block is span-structured, otherwise the whole block as one
        entry). Empty heading or block → skipped.
    """
    sections: dict[str, list[str]] = {}
    for heading_fragment, body in _SECTION_RE.findall(html):
        heading = _plain_markup(heading_fragment)
        if not heading:
            continue
        chips = [text for text in (_plain_markup(s) for s in _SPAN_RE.findall(body)) if text]
        if not chips:
            whole = _plain_markup(body)
            chips = [whole] if whole else []
        if chips:
            sections[heading] = chips
    return sections


def _section_spans(sections: dict[str, list[str]], needle: str) -> list[str]:
    """Spans of the first section whose heading *starts with* ``needle``.

    Prefix matching because Jobinja headings carry ZWNJ (``مهارت‌
    های مورد نیاز``, ``دسته‌بندی شغلی``) that must not be hand-typed,
    and because headings/bodies can *contain* a needle mid-text (the
    description prose mentions "مهارت‌ها", "موقعیت", …) — only a real
    heading starts with its label. Needles are chosen so the
    job-description heading (``شرح موقعیت شغلی``) can never match
    ``موقعیت مکانی``.
    """
    for heading, spans in sections.items():
        if heading.startswith(needle):
            return spans
    return []


def _first_text(value: object) -> str | None:
    """schema.org's union ``Text | Text[]`` — first element, trimmed."""
    if isinstance(value, list):
        for item in value:
            text = _text_or_none(item)
            if text:
                return text
        return None
    return _text_or_none(value)


def _money_value(value: object) -> int | None:
    """``MonetaryAmount.value`` — scalar or ``QuantitativeValue`` dict.

    Observed scalar (``45000000``); the schema also allows
    ``{"value"/"minValue"/"maxValue": …}``, unwrapped here so a shape
    variant degrades to "a number" instead of "no salary".
    """
    if isinstance(value, dict):
        value = value.get("value", value.get("minValue"))
    if value is None or value == "" or value == "None":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class RawJobinjaJob(BaseModel):
    """A single validated job record as parsed from a Jobinja job page.

    Attributes:
        source_job_id: ``identifier.value`` — the numeric job id from
            the JSON-LD, stringified (job-scoped, confirmed: same
            company, 5 jobs, 5 distinct values).
        job_title: ``title`` — employer-written Persian; the translation
            layer handles it downstream.
        company_name: ``hiringOrganization.name``.
        company_logo_url: ``hiringOrganization.logo`` (str, or
            ``ImageObject.url``) — the CDN URL as given.
        description_html: ``description`` — HTML fragment (RTL lists)
            straight from the JSON-LD; the cleaner strips it.
        posting_date: ``datePosted`` (``YYYY-MM-DD`` → UTC midnight).
        closing_date: ``validThrough`` — rarely present (0/10 sampled),
            so usually ``None``.
        employment_type_raw: ``employmentType`` (``FULL_TIME`` observed;
            a schema.org list yields its first member — the full value
            stays in ``raw_payload``).
        base_salary_value: ``baseSalary.value`` as int (scalar or
            ``QuantitativeValue``). Type-coerced only; the ≤0/negotiate
            *semantics* belong to the cleaner.
        salary_currency: ``baseSalary.currency`` (``IRT`` observed —
            Iranian Toman, what the site quotes).
        salary_unit: ``baseSalary.unitText`` (``MONTH`` observed).
        location_spans: chips of the ``موقعیت مکانی`` section
            ("تهران ، تهران").
        salary_text_spans: chips of the ``حقوق`` section — the visible
            salary disclosure ("از ۴۵,۰۰۰,۰۰۰ تومان" / "توافقی").
        skills_spans: chips of ``مهارت‌های مورد نیاز``.
        category_spans: chip of ``دسته‌بندی شغلی`` (category — folded
            into skills by the cleaner, same stance Glints takes with
            its category/industry tags).
        country_code: ``jobLocation.addressCountry.name`` (``IR``).
        is_telecommute: ``jobLocationType == "TELECOMMUTE"``.
        original_url: Injected by the client (the listing's own canonical
            link, tracking params stripped) so the model can treat it
            like every other source's URL.
        raw_payload: ``{"ld": <JobPosting>, "sections": <heading→
            chips>}`` — everything, for auditability.
    """

    source_job_id: str
    job_title: str
    company_name: str
    company_logo_url: str | None = None
    description_html: str | None = None
    posting_date: datetime | None = None
    closing_date: datetime | None = None
    employment_type_raw: str | None = None
    base_salary_value: int | None = None
    salary_currency: str | None = None
    salary_unit: str | None = None
    location_spans: list[str] = []
    salary_text_spans: list[str] = []
    skills_spans: list[str] = []
    category_spans: list[str] = []
    country_code: str | None = None
    is_telecommute: bool = False
    original_url: str
    raw_payload: dict = {}

    @field_validator("source_job_id", "job_title", "company_name", mode="after")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("original_url", mode="after")
    @classmethod
    def _url_non_empty(cls, value: str) -> str:
        # Injected by the client from the listing card; an empty one
        # means the payload lost its canonical URL and the record is
        # unusable (same stance Glints' model takes).
        if not value.strip():
            raise ValueError("original_url must be a non-empty string")
        return value

    @field_validator("base_salary_value", mode="before")
    @classmethod
    def _coerce_salary(cls, value: object) -> int | None:
        if value is None or value == "" or value == "None":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def from_page_html(cls, html: str, *, original_url: str) -> "RawJobinjaJob":
        """Build a validated job from one detail page's raw HTML.

        Raises:
            ValueError: If the page embeds no JSON-LD ``JobPosting`` —
                the parser skips the record (skip-rate bounded), rather
                than a missing block taking down the run.
        """
        job_posting = _extract_job_posting(html)
        sections = _extract_tag_sections(html)

        identifier = job_posting.get("identifier")
        job_id = identifier.get("value") if isinstance(identifier, dict) else identifier

        organization = job_posting.get("hiringOrganization")
        organization = organization if isinstance(organization, dict) else {}
        logo = organization.get("logo")
        if isinstance(logo, dict):
            logo = logo.get("url")

        location = job_posting.get("jobLocation")
        address = location.get("address") if isinstance(location, dict) else {}
        address = address if isinstance(address, dict) else {}
        country = address.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")

        salary = job_posting.get("baseSalary")
        salary = salary if isinstance(salary, dict) else {}
        salary_value = _money_value(salary.get("value"))

        return cls(
            source_job_id=_text_or_none(job_id) or "",
            job_title=_text_or_none(job_posting.get("title")) or "",
            company_name=_text_or_none(organization.get("name")) or "",
            company_logo_url=_text_or_none(logo),
            description_html=_text_or_none(job_posting.get("description")),
            posting_date=_parse_iso_date(job_posting.get("datePosted")),
            closing_date=_parse_iso_date(job_posting.get("validThrough")),
            employment_type_raw=_first_text(job_posting.get("employmentType")),
            base_salary_value=salary_value,
            salary_currency=_text_or_none(salary.get("currency")),
            salary_unit=_text_or_none(salary.get("unitText")),
            location_spans=_section_spans(sections, "موقعیت مکانی"),
            salary_text_spans=_section_spans(sections, "حقوق"),
            skills_spans=_section_spans(sections, "مهارت"),
            category_spans=_section_spans(sections, "دسته"),
            country_code=_text_or_none(country),
            is_telecommute=job_posting.get("jobLocationType") == "TELECOMMUTE",
            original_url=original_url,
            raw_payload={"ld": job_posting, "sections": sections},
        )
