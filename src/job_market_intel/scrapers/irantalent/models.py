"""Typed model for a single raw Irantalent job record.

Mirrors the role ``scrapers/jobvision/models.py`` plays: the raw,
source-specific shape — one search row plus the client's constructed
URL — one step before ``cleaning/irantalent_cleaner.py`` maps it onto
the shared ``CleanedJob``.

Field facts confirmed live (2026-10-07, probes r6-r10; snapshots in
``tests/unit/scrapers/irantalent/test_models.py`` are verbatim rows
184579 [regular] and 184576 [anonymous]):

* **Identity** — ``id`` (int, e.g. ``184579``) is the job id; there is
  no schema.org ``identifier`` and ``redirection_url`` is null on every
  sampled row, so the client constructs
  ``/{en|fa}/job/{slug}/{id}`` from the record's own ``slug`` (SPA
  routes by id; both locale prefixes answer 200) and passes it in.
* **Titles** — bilingual pairs: ``title`` (English) and
  ``title_farsi``, with ``language`` (``en``/``fa``/``multi``) saying
  which is the poster's primary. The model stores the source-language
  title in ``job_title`` (EN for ``language="en"``, Persian otherwise —
  the same "raw title stays source-language, CI translates downstream"
  stance every other source takes; both originals remain in
  ``raw_payload``).
* **``role_description``** — full HTML (``<p dir="rtl">…``/``<br>``
  observed, median 1,445 chars, no ellipsis truncation); may be empty
  on some rows (r7 min=0) ⇒ None, and the cleaner strips the HTML.
* **Dates** — ``lived_at`` (``"2026-10-06 18:05:33"``, when the current
  listing went live) is ``posting_date``; ``created_at`` (date-only,
  first posting) is the fallback; ``expired_at`` (null while live) is
  ``closing_date``. Naive timestamps are assumed UTC — the site's
  Tehran-local wall time is not re-zoned (same documented convention
  Jobvision's model uses).
* **Salary** — ``salary_from``/``salary_to`` are **whole Toman**
  (observed 200,000,000 .. 1,700,000,000, monthly by market
  convention), gated by ``is_show_salary`` (True on 78/78 sampled rows
  carrying bounds; flag-False rows carry null bounds). Raw model keeps
  source units; the ≤0/reversal/withhold rules live in the cleaner.
* **Employment** — ``employment_type`` ``{id, title, title_farsi,
  slug}`` ("Full Time" 178/180, "Part Time", "Freelance" observed;
  no Internship type in the sample) ⇒ ``work_type_en`` is what the
  cleaner maps onto ``ref.employment_types``. ``work_type``
  (``on_site``/``hybrid``) is a separate location-mode field: no
  ``CleanedJob`` slot exists for it, so it stays in ``raw_payload``
  only (the stance Jobvision's cleaner takes with ``isRemote``).
* **Location** — one city: ``location_text_farsi`` / ``location_text``
  (``location`` object carries {id, title, title_farsi, parent{id}} but
  no province/country piece). The model keeps the Persian-first string.
* **Company** — ``employer`` always present: ``name`` (display name —
  "Eways" beside the legal ``title`` "Iranian Omid Internet Bazaar"),
  ``name_farsi``, ``title`` (legal), ``slug``, ``logo_path`` (full
  minio URL), ``industry_id`` (id only — the industry *title* lives on
  ``brand_data.industry``/``anonymous_data.industry`` when those
  nullable blocks are present, which is where tags get it from).
  ``brand_data`` (nullable) adds ``logo_url``; ``anonymous_data``
  (nullable) repeats the generic name for anonymized postings. The
  model resolves company name Persian-first (the stance Jobvision's
  cleaner takes) with fallbacks to "Anonymous".
* **Tag sources** — ``job_category`` is an ARRAY of
  ``{id, title, title_farsi, slug}`` (occupation categories) and the
  nullable ``brand_data``/``anonymous_data`` ``industry`` object
  mirrors that shape ⇒ the model keeps the **English-first** titles
  (``title`` → ``title_farsi``) because ``ref.skills``/the taxonomy
  downstream are English while the site ships parallel labels for
  both languages (documented divergence from Jobvision's
  Persian-first choice, where the EN label was unreliable).
  ``seniority`` (array of levels) and everything else
  (``screening_questions``, ``boosted_at``, ``_score``, …) stay in
  ``raw_payload`` only.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, field_validator


def _text(value: object) -> str | None:
    """Trimmed non-empty string, or None — tolerates ``"None"``/blank."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None":
        return None
    return text


def _iso_date(value: object) -> datetime | None:
    """Parse IranTalent timestamps (``"2026-10-06 18:05:33"`` and
    ``"2026-10-06"`` both observed).

    Naive timestamps are assumed UTC (documented convention — the
    value is Tehran-local wall time kept as-is). Unparseable values
    become ``None`` — honest absence rather than a crash; the batch
    validator flags rows missing a posting date.
    """
    if value is None or value == "" or value == "None":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _money(value: object) -> int | None:
    """Coerce a salary bound to int in **source units** (whole Toman).

    Keeps ``0`` (the cleaner applies the ≤0 → unstated rule); anything
    unparseable becomes ``None``.
    """
    if value is None or value == "" or value == "None":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _localized_list(value: object, *, english_first: bool = False) -> list[str]:
    """``[{title, title_farsi, …}, …]`` → non-empty labels, first-seen order.

    Persian-first by default (``location``-style fields); tag sources
    pass ``english_first=True`` because the downstream taxonomy is
    English (see module docstring).
    """
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            text = _text(item)
            if text:
                out.append(text)
            continue
        if english_first:
            text = _text(item.get("title")) or _text(item.get("title_farsi"))
        else:
            text = _text(item.get("title_farsi")) or _text(item.get("title"))
        if text:
            out.append(text)
    return out


class RawIrantalentJob(BaseModel):
    """A single validated Irantalent job record (search row + URL).

    Attributes:
        source_job_id: The job's ``id``, stringified.
        job_title: The source-language title (``title`` for
            ``language="en"``, else ``title_farsi`` → ``title``).
        language: The row's own ``en``/``fa``/``multi`` label (audit /
            debugging; language detection re-runs downstream anyway).
        company_name: ``employer.name`` (display — "Eways" beside the
            legal ``employer.title``) → ``name_farsi`` → ``title``,
            "Anonymous" when the employer block is missing entirely.
        company_logo_url: ``brand_data.logo_url`` →
            ``employer.logo_path`` (both observed as full minio URLs).
        description_html: ``role_description`` — HTML, source language,
            None when the poster left it empty.
        posting_date: ``lived_at`` (current listing's go-live), falling
            back to ``created_at`` (date-only).
        closing_date: ``expired_at`` (null while live).
        work_type_en: ``employment_type.title`` ("Full Time" observed;
            "Part Time"/"Freelance" also seen) — the field the cleaner
            maps onto ``ref.employment_types``.
        salary_min_raw / salary_max_raw: ``salary_from``/``salary_to``
            in **whole Toman** (source units; no scaling anywhere).
        salary_show_flag: ``is_show_salary`` (True/False observed; the
            cleaner's withhold gate — flag-False rows carry null bounds,
            so a False-with-bounds row is treated as site-withheld).
        location_text: ``location_text_farsi`` → ``location_text``
            (one city, e.g. "تهران").
        category_raws: ``job_category[]`` **English-first** titles.
        industry_raws: ``brand_data``/``anonymous_data``
            ``industry`` titles when those nullable blocks are present
            (English-first; the employer level ships only
            ``industry_id``, so rows without either block contribute
            nothing here).
        original_url: Constructed by the client from the row's
            ``slug``/``id``/``language``.
        raw_payload: The complete search row dict, for audit.
    """

    source_job_id: str
    job_title: str
    language: str | None = None
    company_name: str
    company_logo_url: str | None = None
    description_html: str | None = None
    posting_date: datetime | None = None
    closing_date: datetime | None = None
    work_type_en: str | None = None
    salary_min_raw: int | None = None
    salary_max_raw: int | None = None
    salary_show_flag: bool | None = None
    location_text: str | None = None
    category_raws: list[str] = []
    industry_raws: list[str] = []
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
        # Constructed by the client from slug/id/language; an empty one
        # means the row lost its identity (the same stance Jobvision's
        # model takes on the injected sitemap URL).
        if not value.strip():
            raise ValueError("original_url must be a non-empty string")
        return value

    @classmethod
    def from_payload(cls, payload: object, *, original_url: str) -> RawIrantalentJob:
        """Build the model from one search ``data`` dict.

        Raises:
            ValueError: If the payload is not a JSON object (the
                parser turns that into a skip).
        """
        if not isinstance(payload, dict):
            raise ValueError(f"payload must be a JSON object, got {type(payload).__name__}")

        language = _text(payload.get("language"))
        title_en = _text(payload.get("title"))
        title_fa = _text(payload.get("title_farsi"))
        # Source-language title: English jobs keep the English title,
        # everything else (fa/multi/missing label) prefers Persian —
        # the same raw-stays-source rule every other source follows.
        job_title = (title_en if language == "en" else None) or title_fa or title_en

        employer = payload.get("employer")
        employer = employer if isinstance(employer, dict) else {}
        brand = payload.get("brand_data")
        brand = brand if isinstance(brand, dict) else {}
        anonymous = payload.get("anonymous_data")
        anonymous = anonymous if isinstance(anonymous, dict) else {}
        employment = payload.get("employment_type")
        employment = employment if isinstance(employment, dict) else {}

        # employer.name is the DISPLAY name ("Eways") — employer.title
        # is the legal name ("Iranian Omid Internet Bazaar"); Persian
        # first, the stance Jobvision's cleaner takes.
        company_name = (
            _text(employer.get("name_farsi"))
            or _text(employer.get("name"))
            or _text(employer.get("title"))
            or "Anonymous"
        )
        company_logo_url = _text(brand.get("logo_url")) or _text(employer.get("logo_path"))

        location_text = _text(payload.get("location_text_farsi")) or _text(
            payload.get("location_text")
        )

        # Industry title lives on the nullable brand/anonymous blocks
        # (employer level ships only industry_id); reuse the category
        # list-shape helper so a bare dict or a list both work.
        industry_source = [
            item for item in (brand.get("industry"), anonymous.get("industry")) if item is not None
        ]

        return cls(
            source_job_id=str(payload.get("id") or ""),
            job_title=job_title or "",
            language=language,
            company_name=company_name,
            company_logo_url=company_logo_url,
            description_html=_text(payload.get("role_description")),
            posting_date=_iso_date(payload.get("lived_at")) or _iso_date(payload.get("created_at")),
            closing_date=_iso_date(payload.get("expired_at")),
            work_type_en=_text(employment.get("title")),
            salary_min_raw=_money(payload.get("salary_from")),
            salary_max_raw=_money(payload.get("salary_to")),
            salary_show_flag=payload.get("is_show_salary")
            if isinstance(payload.get("is_show_salary"), bool)
            else None,
            location_text=location_text,
            category_raws=_localized_list(payload.get("job_category"), english_first=True),
            industry_raws=_localized_list(industry_source, english_first=True),
            original_url=original_url,
            raw_payload=payload,
        )
