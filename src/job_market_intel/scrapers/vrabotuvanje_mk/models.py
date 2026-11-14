"""Raw data models for Vrabotuvanje (North Macedonia)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RawVrabotuvanjeMkJob:
    """Raw job metadata and deserialized Nuxt 3 data for a job posting."""

    uuid: str
    slug: str
    url: str
    data: dict[str, Any] = field(default_factory=dict)
    raw_html: Optional[str] = field(default=None, repr=False)
