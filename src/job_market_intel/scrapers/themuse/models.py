"""Typed models for raw The Muse API records.

The Muse nests where most feeds flatten: ``company`` is an object, ``levels``
and ``locations`` are lists of objects, and the description lives in
``contents`` as HTML. The properties at the bottom flatten that once, here,
so the cleaner and parser do not each re-derive it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RawThemuseJob(BaseModel):
    """One posting as returned by ``GET /api/public/jobs``."""

    id: str = Field(..., description="Numeric id, stringified; the stable identity.")
    name: str = Field(..., description="Job title.")
    company: dict[str, Any] | None = Field(
        default=None, description="{id, name, short_name}."
    )
    contents: str | None = Field(default=None, description="HTML description.")
    publication_date: str | None = Field(
        default=None, description="ISO-8601 publication timestamp."
    )
    categories: list[dict[str, Any]] = Field(default_factory=list)
    levels: list[dict[str, Any]] = Field(default_factory=list)
    locations: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[dict[str, Any]] = Field(default_factory=list)
    refs: dict[str, Any] = Field(default_factory=dict)

    raw_payload: dict[str, Any] = Field(
        default_factory=dict, description="Verbatim original record, for audit."
    )

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_id(cls, value: Any) -> Any:
        """``core.jobs.source_job_id`` is text, so normalise once at the edge."""
        return str(value) if value is not None else value

    @field_validator("name", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @property
    def source_job_id(self) -> str:
        """Identity in the shared vocabulary ``validate_batch`` expects."""
        return self.id

    @property
    def company_name(self) -> str | None:
        if not isinstance(self.company, dict):
            return None
        value = self.company.get("name")
        return value.strip() if isinstance(value, str) and value.strip() else None

    @property
    def location_text(self) -> str | None:
        """Comma-join the ``name`` of each location object."""
        names = [
            str(loc["name"]).strip()
            for loc in self.locations
            if isinstance(loc, dict) and loc.get("name")
        ]
        return ", ".join(names) or None

    @property
    def level_text(self) -> str | None:
        names = [
            str(lvl["name"]).strip()
            for lvl in self.levels
            if isinstance(lvl, dict) and lvl.get("name")
        ]
        return ", ".join(names) or None

    @property
    def category_text(self) -> str | None:
        names = [
            str(cat["name"]).strip()
            for cat in self.categories
            if isinstance(cat, dict) and cat.get("name")
        ]
        return ", ".join(names) or None

    @property
    def apply_url(self) -> str | None:
        landing = self.refs.get("landing_page") if isinstance(self.refs, dict) else None
        return landing if isinstance(landing, str) and landing else None

    @property
    def posting_date(self) -> dt.datetime | None:
        """``publication_date`` parsed, or None when absent or unparseable."""
        if not self.publication_date:
            return None
        text = str(self.publication_date).strip().replace("Z", "+00:00")
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
        # A naive timestamp stored as-is would be interpreted as UTC and shift
        # the posting date, so the offset is asserted rather than assumed.
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
