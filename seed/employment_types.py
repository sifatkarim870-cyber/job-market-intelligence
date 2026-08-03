"""Seeds ref.employment_types."""
from __future__ import annotations

from sqlalchemy import Connection

from .base import SeedResult, upsert_many

EMPLOYMENT_TYPES = [
    {"code": "full_time", "label": "Full-time", "description": "Standard full-time employment.", "sort_order": 1},
    {"code": "part_time", "label": "Part-time", "description": "Reduced-hours employment.", "sort_order": 2},
    {"code": "contract", "label": "Contract", "description": "Fixed-term or project-based engagement.", "sort_order": 3},
    {"code": "temporary", "label": "Temporary", "description": "Short-term employment covering a specific need.", "sort_order": 4},
    {"code": "internship", "label": "Internship", "description": "Structured, typically time-boxed learning role.", "sort_order": 5},
    {"code": "freelance", "label": "Freelance", "description": "Independent-contractor, typically per-project.", "sort_order": 6},
    {"code": "apprenticeship", "label": "Apprenticeship", "description": "Combined work/training program.", "sort_order": 7},
]


def seed_employment_types(conn: Connection) -> SeedResult:
    return upsert_many(
        conn, schema="ref", table_name="employment_types",
        rows=EMPLOYMENT_TYPES, conflict_cols=("code",),
    )