"""Raw data models for FINN.no."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RawFinnNoJob:
    """Raw job metadata and JSON-LD extracted from FINN.no."""

    job_id: str
    url: str
    json_ld: dict[str, Any] = field(default_factory=dict)
    raw_html: Optional[str] = field(default=None, repr=False)
