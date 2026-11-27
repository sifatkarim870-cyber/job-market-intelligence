"""Data models for the Robota.ua (robota.ua, Ukraine) scraper.

The GraphQL ``publishedVacancies`` response is already the full public
record, so unlike the HTML sources there is no second detail fetch: the
client keeps the raw payload dictionary verbatim and the parser maps it onto
the shared ``CleanedJob``. Keeping the whole payload here is also what the
platform's "never discard original source data" rule asks for -- it becomes
``CleanedJob.raw_payload`` unchanged.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawRobotaUaJob(BaseModel):
    """One ``publishedVacancies`` item plus its canonical URL."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    url: str
    payload: dict[str, Any]

    @classmethod
    def from_item(cls, item: dict[str, Any], *, base_url: str) -> RawRobotaUaJob:
        """Build the model from one GraphQL item.

        Raises:
            ValueError: If the item has no usable ``id`` or ``title``; the
                client turns that into a skip rather than a crash.
        """
        job_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        if not job_id or not title:
            raise ValueError("vacancy item must carry a non-empty id and title")
        return cls(
            job_id=job_id,
            url=f"{base_url.rstrip('/')}/vacancy/{job_id}",
            payload=item,
        )


class RobotaUaPipelineRunResult(BaseModel):
    """Execution summary for a Robota.ua scraper run."""

    raw_count: int = Field(default=0)
    parsed_count: int = Field(default=0)
    validation_passed: bool = Field(default=False)
    cleaned_count: int = Field(default=0)
    pages_scraped: int = Field(default=0)
    inserted_count: int = Field(default=0)
    updated_count: int = Field(default=0)
    unchanged_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    session_id: int | None = Field(default=None)
    issues: list[str] = Field(default_factory=list)
