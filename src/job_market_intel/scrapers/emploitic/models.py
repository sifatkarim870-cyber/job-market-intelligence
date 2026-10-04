"""Typed model for a single raw Emploitic job record.

Mirrors the role ``scrapers/remotive/models.py`` plays for Remotive: the
raw, source-specific shape, one step before
``cleaning/emploitic_cleaner.py`` maps it onto the shared ``CleanedJob``.

Field facts confirmed live (2026-10-04): ``location``, ``contractType``,
``jobLevel``, ``educationLevel`` and ``experienceYears`` are lists of
``{id, arn, label, lang, metadata}`` objects — the first entry's
``label`` is used; ``workMode`` is a bare string (``"onsite"`` observed);
``company`` may be missing for anonymous postings (``isAnonymous:
true``); there is no salary field on the listing payload, so salary
stays ``None`` for every Emploitic record.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _first_label(value: object) -> str | None:
    """Return the first entry's ``label`` from an Emploitic labelled-list, or None."""
    if isinstance(value, list) and value and isinstance(value[0], dict):
        label = value[0].get("label")
        if isinstance(label, str) and label.strip():
            return label.strip()
    return None


class RawEmploiticJob(BaseModel):
    """A single validated job record as returned by Emploitic's payload.

    Attributes:
        source_job_id: Emploitic's UUID ``id``, stringified.
        job_title: Raw ``title``.
        company_name: Raw ``company.name`` — falls back to "Anonymous"
            when the posting is anonymous and no name is present.
        company_sector_raw: ``company.sector.label`` — raw hint, resolved
            to a canonical industry by a later normalization step.
        contract_type_raw: First ``contractType[].label`` (e.g.
            "CDD Ou Mission", "CDI").
        work_mode_raw: ``workMode`` (e.g. "onsite", "remote",
            "hybrid").
        job_level_raw: First ``jobLevel[].label``.
        profession_raw: ``profession`` label (list or dict shape-tolerant).
        location_raw: First ``location[].label`` (e.g. "Alger, Algérie").
        tags: ``tags`` list, defaulting to empty.
        description_raw: HTML ``description``.
        original_url: Canonical posting URL on emploitic.com, built from
            ``alias`` (``/offres-d-emploi/{alias}`` redirects to the full
            sector-prefixed URL — confirmed live).
        posting_date: Parsed ISO-8601 ``publishedAt``.
        raw_payload: The complete original record, kept for auditability.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    source_job_id: str = Field(alias="id", min_length=1)
    job_title: str = Field(alias="title", min_length=1)
    company_name: str = Field(min_length=1)
    company_sector_raw: str | None = None
    contract_type_raw: str | None = None
    work_mode_raw: str | None = Field(default=None, alias="workMode")
    job_level_raw: str | None = None
    profession_raw: str | None = None
    location_raw: str | None = None
    tags: list[str] = Field(default_factory=list)
    description_raw: str | None = Field(default=None, alias="description")
    original_url: str = Field(min_length=1)
    posting_date: datetime | None = Field(default=None, alias="publishedAt")
    raw_payload: dict = Field(default_factory=dict, exclude=False)

    @field_validator("source_job_id", mode="before")
    @classmethod
    def _stringify_id(cls, value: object) -> str:
        if value is None:
            raise ValueError("id must not be null")
        text = str(value).strip()
        if not text:
            raise ValueError("id must not be empty")
        return text

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(entry) for entry in value]
        return []

    @field_validator("posting_date", mode="before")
    @classmethod
    def _parse_iso_date(cls, value: object) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        return None

    @classmethod
    def from_listing_entry(cls, entry: dict) -> RawEmploiticJob:
        """Build a validated job from one ``searchResult.data`` entry.

        Kept explicit (rather than alias-driven) because the payload's
        nesting — ``company.name``, ``location[0].label``, … — can't be
        expressed with plain field aliases, and because ``original_url``
        has to be constructed from ``alias``.
        """
        company = entry.get("company") or {}
        sector = company.get("sector") or {}
        company_name = company.get("name") or ""
        if not isinstance(company_name, str) or not company_name.strip():
            company_name = "Anonymous"
        profession = entry.get("profession")
        if isinstance(profession, list):
            profession = _first_label(profession)
        elif isinstance(profession, dict):
            profession = profession.get("label")
        alias = entry.get("alias")
        original_url = (
            f"https://emploitic.com/offres-d-emploi/{alias}"
            if isinstance(alias, str) and alias.strip()
            else ""
        )
        return cls(
            id=entry.get("id", ""),
            title=entry.get("title", "") or "",
            company_name=company_name.strip(),
            company_sector_raw=sector.get("label") if isinstance(sector, dict) else None,
            contract_type_raw=_first_label(entry.get("contractType")),
            workMode=entry.get("workMode"),
            job_level_raw=_first_label(entry.get("jobLevel")),
            profession_raw=profession if isinstance(profession, str) else None,
            location_raw=_first_label(entry.get("location")),
            tags=entry.get("tags") or [],
            description=entry.get("description"),
            original_url=original_url,
            publishedAt=entry.get("publishedAt"),
            raw_payload=entry,
        )
