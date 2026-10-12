"""Typed models for raw Himalayas API records.

Field names mirror the API exactly. Every optional field is genuinely optional
in practice: probing the live feed on 2026-10-12 showed records with no
``minSalary``, no ``salaryPeriod``, and an empty ``locationRestrictions`` list,
so none of them can be required without silently dropping real postings.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RawHimalayasJob(BaseModel):
    """One posting as returned by ``GET /jobs/api``."""

    guid: str = Field(..., description="Canonical job URL; the stable identity.")
    title: str = Field(..., description="Job title.")
    companyName: str | None = Field(default=None, description="Employer name.")
    companyLogo: str | None = Field(default=None, description="Employer logo URL.")
    companySlug: str | None = Field(default=None, description="Employer slug.")
    description: str | None = Field(default=None, description="HTML description.")
    excerpt: str | None = Field(default=None, description="Plain-text summary.")
    locationRestrictions: list[str] = Field(
        default_factory=list, description="Allowed countries/regions."
    )
    employmentType: str | None = Field(default=None, description="e.g. 'Full-Time'.")
    seniority: list[str] = Field(default_factory=list, description="Seniority levels.")
    categories: list[str] = Field(default_factory=list, description="Job categories.")
    parentCategories: list[str] = Field(default_factory=list, description="Broad category.")
    minSalary: float | None = Field(default=None, description="Lower salary bound.")
    maxSalary: float | None = Field(default=None, description="Upper salary bound.")
    currency: str | None = Field(default=None, description="ISO currency code.")
    salaryPeriod: str | None = Field(default=None, description="e.g. 'hourly'.")
    pubDate: int | None = Field(default=None, description="Unix seconds of publication.")
    expiryDate: int | None = Field(default=None, description="Unix seconds of expiry.")
    applicationLink: str | None = Field(default=None, description="Apply URL.")

    raw_payload: dict[str, Any] = Field(
        default_factory=dict, description="Verbatim original record, for audit."
    )

    @field_validator("guid", "title", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @property
    def source_job_id(self) -> str:
        """The identity ``source_job_id`` in the shared vocabulary.

        ``validation.common.validate_batch`` counts duplicate identities via
        this attribute on every source's model, so every model has to expose
        it. For Himalayas the natural key is ``guid`` (see the module
        docstring), so this is an alias rather than a separate field.
        """
        return self.guid

    @property
    def posting_date(self) -> dt.datetime | None:
        """``pubDate`` as a UTC datetime, or None when absent/unparseable."""
        if not self.pubDate:
            return None
        try:
            return dt.datetime.fromtimestamp(self.pubDate, tz=dt.UTC)
        except (OverflowError, OSError, ValueError):
            return None

    @property
    def closing_date(self) -> dt.datetime | None:
        if not self.expiryDate:
            return None
        try:
            return dt.datetime.fromtimestamp(self.expiryDate, tz=dt.UTC)
        except (OverflowError, OSError, ValueError):
            return None

    @property
    def location_text(self) -> str | None:
        """A single location string, or None when the posting is unrestricted."""
        return ", ".join(self.locationRestrictions) or None
