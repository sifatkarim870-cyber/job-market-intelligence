"""Raw data model for a single Ajira TZ vacancy."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RawAjiraTzJob:
    """Minimal parsed representation of one Ajira Portal Tanzania vacancy."""

    vacancy_id: int
    scheme_id: Optional[int]
    scheme_code_no: Optional[str]        # vacancy title / post name
    employer_id: Optional[int]
    employer_name: Optional[str]
    duties_html: Optional[str]
    qualifications_html: Optional[str]
    salary_scale_name: Optional[str]
    open_date: Optional[str]             # ISO datetime string e.g. "2026-11-13T00:00"
    close_date: Optional[str]
    no_of_post: Optional[int]
    status_text: Optional[str]
    raw: dict = field(default_factory=dict, repr=False)
