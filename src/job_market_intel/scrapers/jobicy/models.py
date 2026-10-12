"""Typed models for raw Jobicy API records."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RawJobicyJob(BaseModel):
    """One posting as returned by ``GET /api/v2/remote-jobs``."""

    id: str = Field(..., description="Numeric id, stringified; the stable identity.")
    jobTitle: str = Field(..., description="Job title.")
    companyName: str | None = Field(default=None, description="Employer name.")
    companyLogo: str | None = Field(default=None, description="Employer logo URL.")
    jobGeo: str | None = Field(
        default=None, description="Normalised region, e.g. 'USA' or 'Europe'."
    )
    jobIndustry: list[str] = Field(default_factory=list, description="Industry tags.")
    jobType: list[str] = Field(
        default_factory=list, description="e.g. ['Full-Time']."
    )
    jobLevel: str | None = Field(default=None, description="Seniority label.")
    jobDescription: str | None = Field(default=None, description="HTML description.")
    jobExcerpt: str | None = Field(default=None, description="Plain-text summary.")
    pubDate: str | None = Field(default=None, description="ISO-8601 publication time.")
    url: str | None = Field(default=None, description="Apply URL.")

    raw_payload: dict[str, Any] = Field(
        default_factory=dict, description="Verbatim original record, for audit."
    )

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_id(cls, value: Any) -> Any:
        """The API returns ``id`` as a number; the natural key is text.

        ``core.jobs.source_job_id`` is text, so an int here would be cast by
        the driver anyway -- but doing it once, here, means the value logged
        during parsing matches the value stored.
        """
        return str(value) if value is not None else value

    @field_validator("jobTitle", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @property
    def source_job_id(self) -> str:
        """Identity in the shared vocabulary ``validate_batch`` expects."""
        return self.id

    @property
    def posting_date(self) -> dt.datetime | None:
        """``pubDate`` parsed, or None when absent or unparseable."""
        if not self.pubDate:
            return None
        text = str(self.pubDate).strip().replace("Z", "+00:00")
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
        # Every observed value carries an offset, but a naive datetime would be
        # stored as if it were UTC and silently shift the posting date.
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
