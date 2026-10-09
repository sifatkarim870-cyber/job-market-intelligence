"""Typed model for one Greenhouse posting, as Greenhouse itself returns it.

``source_job_id`` is the one deliberate rename: every other source's raw model
exposes ``source_job_id`` (aliased from the vendor field), and
``validation.common.HasSourceJobId`` depends on that name to run
within-batch duplicate detection. Naming it ``id`` here made the first live
pipeline run die with "'RawGreenhouseJob' object has no attribute
'source_job_id'" after the fetch and parse stages had already succeeded.

The remaining fields keep GREENHOUSE's naming, as every other source's raw
model does, so a vendor change shows up as one obvious diff here rather than
being scattered across cleaning and validation.

``content`` holds the full job description as HTML. It is the single most
valuable field in the payload and the reason Greenhouse is worth a dedicated
source -- these are complete, structured, English descriptions, not teasers.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class RawGreenhouseJob(BaseModel):
    """One posting exactly as Greenhouse's public board API returns it."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    source_job_id: str = Field(
        ...,
        alias="id",
        min_length=1,
        description="Greenhouse's own numeric posting id, as a string. Stable per "
        "posting, and the natural key that makes re-runs idempotent.",
    )
    title: str = Field(..., min_length=1, description="Posting title as the employer wrote it.")
    updated_at: datetime | None = Field(
        default=None, description="When the employer last edited this posting."
    )
    first_published: datetime | None = Field(
        default=None, description="When the posting first went live."
    )
    absolute_url: str = Field(default="", description="Public apply URL for this posting.")
    location: dict = Field(
        default_factory=dict,
        description="e.g. {'name': 'Remote, France'}. Free text, not a code.",
    )
    departments: list[dict] = Field(
        default_factory=list,
        description="Department hierarchy, each with parent_id.",
    )
    offices: list[dict] = Field(
        default_factory=list,
        description="Office/location records, each carrying a country-ish 'location'.",
    )
    metadata: list[dict] = Field(
        default_factory=list,
        description="Employer-defined custom fields (Quota Coverage Type, Team, ...).",
    )
    company_name: str = Field(default="", description="Board owner, e.g. 'GitLab'.")
    requisition_id: str | None = Field(default=None)
    internal_job_id: str | None = Field(default=None)

    @field_validator("source_job_id", "requisition_id", "internal_job_id", mode="before")
    @classmethod
    def _coerce_id(cls, value: object) -> str | None:
        """Greenhouse sends these as INTEGERS (e.g. id=8860302002,
        internal_job_id=6547054002), not strings, and the type flips between
        boards.

        Declaring them ``str`` without this coercion made pydantic reject 100%
        of real postings -- the first live run dropped 1,000 of 1,000 records
        before a single row reached the database. ``source_job_id`` needs the
        same treatment: it is populated from the ``id`` ALIAS, and a
        mode="before" validator keyed on the field name sees the alias value
        before the alias is resolved.
        """
        if value is None or value == "":
            return None
        return str(value)

    language: str | None = Field(default=None, description="ISO code when Greenhouse knows it.")
    content: str = Field(default="", description="Full description HTML.")

    @field_validator("departments", "offices", "metadata", "location", mode="before")
    @classmethod
    def _null_to_empty(cls, value: object, info: ValidationInfo) -> object:
        """Treat a JSON ``null`` as "absent" for the collection fields.

        A pydantic ``default_factory`` only applies when the key is MISSING.
        Greenhouse sends these keys present-but-null (``"metadata": null``),
        which then failed type validation -- the first live run parsed 269 of
        1,000 records and dropped 731 for exactly this reason.
        """
        if value is not None:
            return value
        return {} if info.field_name == "location" else []

    @property
    def location_name(self) -> str:
        """The human-readable location string, which is all Greenhouse gives us."""
        name = self.location.get("name") if isinstance(self.location, dict) else None
        return str(name or "").strip()

    @property
    def office_names(self) -> list[str]:
        """Office names, used as a secondary location signal.

        A posting's ``location.name`` is employer free text ("Remote, France")
        while ``offices`` is Greenhouse's own structured list; when the first is
        vague the second usually carries the country.
        """
        names: list[str] = []
        for office in self.offices:
            if isinstance(office, dict):
                value = office.get("name") or office.get("location")
                if value:
                    names.append(str(value))
        return names

    @property
    def department_names(self) -> list[str]:
        names: list[str] = []
        for dept in self.departments:
            if isinstance(dept, dict) and dept.get("name"):
                names.append(str(dept["name"]))
        return names
