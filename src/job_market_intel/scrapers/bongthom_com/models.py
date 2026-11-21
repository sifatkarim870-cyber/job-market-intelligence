"""Typed model for a single raw BongThom job record.

Mirrors the role ``scrapers/blmis_bt/models.py`` plays: the raw,
source-specific shape -- one merged discovery row plus its structured
``get_embed`` detail and its rendered "Workplace Circumstances" -- one step
before ``cleaning/bongthom_com_cleaner.py`` maps it onto the shared
``CleanedJob``.

Field facts confirmed live (2026-11-21; the worked record in
``tests/unit/scrapers/test_bongthom_com.py`` is a real one, job ``42739``):

* **Identity** -- ``id`` is an integer on both the discovery row and the
  embed; it is the stable ``source_job_id``. The public page is
  ``https://bongthom.com/job_detail/view_detail_<id>.html``, which is what
  ``original_url`` stores.
* **Titles/company** -- the discovery row and the embed both carry
  ``title`` / ``company`` / ``logo``; the embed is preferred, with the
  discovery row as the fallback for a job whose embed GET failed.
* **Description content** -- the embed's ``positions[]`` carry an HTML
  ``description`` plus separate prose arrays: ``duties[].text``,
  ``benefits[].benefit``, ``qualifications[].major`` and
  ``experiences[].position``. They are kept as separate lists here so the
  cleaner can fold them into one description in a stable order.
* **Skills** -- ``skill_knowledges[].skill`` are the posting's skill /
  requirement strings (``skill_type`` is ``"language"``, ``"soft"`` or
  ``"hard"``); the model keeps the text regardless of type.
* **Experience** -- ``experiences[].years`` is whole years (nullable); the
  model keeps every non-null value so the cleaner can take the minimum.
* **Location/salary/schedule** -- these live only on the rendered page's
  "Workplace Circumstances" list, which the client parses into a
  ``workplace`` dict and passes here. ``location_text`` is the work
  location(s) joined with ``"; "`` (a multi-position posting repeats the
  block per position), ``salary_text_raw`` the first "Salary:" value and
  ``employment_type_raw`` the first "Schedule:" value.
* **Categories** -- ``categories[].name_en`` from the embed are merged with
  the rendered "Career Category:" values (a multi-position posting repeats
  them), de-duplicated, for audit.
* **Dates** -- ``start_date`` / ``close_date`` are ``"2026-11-30
  00:00:00"``; naive values are assumed UTC (the documented repo
  convention).
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, field_validator

#: A logo path the board serves for a company that uploaded none.
_PLACEHOLDER_LOGO_MARKER = "error_pic"


def _text(value: object) -> str | None:
    """Trimmed non-empty string, or None -- tolerates ``"None"``/blank."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None":
        return None
    return text


def _int(value: object) -> int | None:
    """Coerce to int, or None when unparseable/absent (keeps 0)."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _parse_date(value: object) -> datetime | None:
    """Parse ``"2026-11-30 00:00:00"`` as aware UTC.

    Naive values are assumed UTC (documented convention). Unparseable
    values become ``None`` -- honest absence rather than a crash.
    """
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _logo_url(*candidates: object) -> str | None:
    """First usable logo URL, dropping the board's ``error_pic`` placeholder."""
    for candidate in candidates:
        text = _text(candidate)
        if text and _PLACEHOLDER_LOGO_MARKER not in text:
            return text
    return None


def _dedupe(values: list[str]) -> list[str]:
    """De-duplicate strings preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _position_list(embed: dict, key: str) -> list[dict]:
    """Flatten ``positions[].<key>`` lists into one list of dicts."""
    out: list[dict] = []
    for position in embed.get("positions") or []:
        if not isinstance(position, dict):
            continue
        items = position.get(key)
        if isinstance(items, list):
            out.extend(item for item in items if isinstance(item, dict))
    return out


def _text_field(items: list[dict], key: str) -> list[str]:
    """Collect one trimmed string field across a flattened item list."""
    out: list[str] = []
    for item in items:
        value = _text(item.get(key))
        if value:
            out.append(value)
    return out


class RawBongthomJob(BaseModel):
    """A single validated BongThom job record (discovery + embed + rendered page).

    Attributes:
        source_job_id: The job's ``id``, stringified.
        job_title: Embed ``title`` -> discovery ``title``.
        company_name: Embed ``company`` -> discovery ``company``.
        company_logo_url: Embed/discovery ``logo``, with the board's
            ``error_pic`` placeholder dropped.
        description_htmls: HTML ``positions[].description`` values.
        duty_texts: ``positions[].duties[].text`` values.
        benefit_texts: ``positions[].benefits[].benefit`` values.
        qualification_texts: ``positions[].qualifications[].major`` values.
        experience_texts: ``positions[].experiences[].position`` values.
        skills_raw: ``positions[].skill_knowledges[].skill`` values.
        experience_years_raw: ``positions[].experiences[].years`` values
            (non-null), for the cleaner's minimum.
        categories_raw: Embed ``categories[].name_en`` merged with the
            rendered "Career Category:" values, de-duplicated.
        location_text: Rendered "Location:" value(s), joined ``"; "``.
        salary_text_raw: Rendered "Salary:" value (e.g. ``"$350 - $450
            Negotiable"`` or ``"Negotiable"``).
        employment_type_raw: Rendered "Schedule:" value (e.g.
            ``"Full-time"``).
        posting_date: ``start_date``.
        closing_date: ``close_date``.
        original_url: The public detail page URL.
        raw_payload: ``{"listing": ..., "embed": ..., "workplace": ...}``
            for audit.
    """

    source_job_id: str
    job_title: str
    company_name: str
    company_logo_url: str | None = None
    description_htmls: list[str] = []
    duty_texts: list[str] = []
    benefit_texts: list[str] = []
    qualification_texts: list[str] = []
    experience_texts: list[str] = []
    skills_raw: list[str] = []
    experience_years_raw: list[int] = []
    categories_raw: list[str] = []
    location_text: str | None = None
    salary_text_raw: str | None = None
    employment_type_raw: str | None = None
    posting_date: datetime | None = None
    closing_date: datetime | None = None
    original_url: str
    raw_payload: dict

    @field_validator("source_job_id", "job_title", mode="after")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("original_url", mode="after")
    @classmethod
    def _url_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("original_url must be a non-empty string")
        return value

    @classmethod
    def from_payload(
        cls,
        listing: object,
        embed: object,
        workplace: object,
        *,
        original_url: str,
    ) -> RawBongthomJob:
        """Build the model from one discovery row, embed and workplace dict.

        Args:
            listing: The discovery row dict (required -- it carries the id).
            embed: The ``get_embed`` dict, or None when that GET failed.
            workplace: The rendered-page dict ``{"locations": [...],
                "salary": ..., "schedule": ..., "categories": [...]}``, or
                None/empty when that GET failed.
            original_url: The public detail page URL.

        Raises:
            ValueError: If ``listing`` is not a JSON object (the parser
                turns that into a skip) or carries no id.
        """
        if not isinstance(listing, dict):
            raise ValueError(f"listing must be a JSON object, got {type(listing).__name__}")
        embed_dict = embed if isinstance(embed, dict) else {}
        workplace_dict = workplace if isinstance(workplace, dict) else {}

        job_id = _text(listing.get("id")) or _text(embed_dict.get("id"))
        if job_id is None:
            raise ValueError("listing carries no id")

        duty_items = _position_list(embed_dict, "duties")
        benefit_items = _position_list(embed_dict, "benefits")
        qualification_items = _position_list(embed_dict, "qualifications")
        experience_items = _position_list(embed_dict, "experiences")
        skill_items = _position_list(embed_dict, "skill_knowledges")

        embed_categories = _text_field(_position_list(embed_dict, "categories"), "name_en")

        rendered_categories = [
            str(value) for value in (workplace_dict.get("categories") or []) if value
        ]
        categories_raw = _dedupe(embed_categories + rendered_categories)

        experience_years_raw = [
            years
            for years in (_int(item.get("years")) for item in experience_items)
            if years is not None
        ]

        locations = [str(value) for value in (workplace_dict.get("locations") or []) if value]
        location_text = "; ".join(_dedupe(locations)) or None

        return cls(
            source_job_id=job_id,
            job_title=_text(embed_dict.get("title")) or _text(listing.get("title")) or "",
            company_name=_text(embed_dict.get("company")) or _text(listing.get("company")) or "",
            company_logo_url=_logo_url(embed_dict.get("logo"), listing.get("logo")),
            description_htmls=_text_field(
                [item for item in (embed_dict.get("positions") or []) if isinstance(item, dict)],
                "description",
            ),
            duty_texts=_text_field(duty_items, "text"),
            benefit_texts=_text_field(benefit_items, "benefit"),
            qualification_texts=_text_field(qualification_items, "major"),
            experience_texts=_text_field(experience_items, "position"),
            skills_raw=_text_field(skill_items, "skill"),
            experience_years_raw=experience_years_raw,
            categories_raw=categories_raw,
            location_text=location_text,
            salary_text_raw=_text(workplace_dict.get("salary")),
            employment_type_raw=_text(workplace_dict.get("schedule")),
            posting_date=_parse_date(embed_dict.get("start_date"))
            or _parse_date(listing.get("start_date")),
            closing_date=_parse_date(embed_dict.get("close_date"))
            or _parse_date(listing.get("close_date")),
            original_url=original_url,
            raw_payload={"listing": listing, "embed": embed_dict, "workplace": workplace_dict},
        )
