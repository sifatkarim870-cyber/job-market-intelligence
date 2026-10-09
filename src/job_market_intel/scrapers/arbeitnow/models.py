"""Typed model for one Arbeitnow posting, as Arbeitnow itself returns it.

Two things about this payload are worth calling out because they shape the
cleaner:

    - There is no numeric ``id``. The natural key is ``slug``, a human-readable
      per-job string that is stable for the life of the posting, so that is what
      ``source_job_id`` is aliased from.
    - ``created_at`` is a UNIX TIMESTAMP (seconds), not an ISO string, which is
      the one field here that needs real conversion rather than parsing.

``description`` is HTML, and ``job_types``/``tags`` are lists that arrive empty
on most postings -- both are handled by the cleaner, not by this model.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RawArbeitnowJob(BaseModel):
    """One posting exactly as Arbeitnow's API returns it."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    source_job_id: str = Field(
        ...,
        alias="slug",
        min_length=1,
        description="Arbeitnow's per-job slug. The only stable identifier this "
        "API provides, so it is the natural key.",
    )
    title: str = Field(..., min_length=1)
    company_name: str = Field(default="")
    description: str = Field(default="", description="Full job description as HTML.")
    location: str | None = Field(default=None)
    remote: bool = Field(default=False)
    url: str = Field(
        default="",
        description="Public page for this posting; also where a human applies.",
    )
    job_types: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime | None = Field(
        default=None,
        description="When the posting was published, converted from a unix timestamp.",
    )

    @property
    def is_remote(self) -> bool:
        """Arbeitnow's own remote flag, which is more reliable than parsing
        ``location`` for the word 'remote'."""
        return bool(self.remote)
