"""Seeds ref.experience_levels, including min/max_years for ordinal ML
encoding as called out in the design doc."""
from __future__ import annotations

from sqlalchemy import Connection

from .base import SeedResult, upsert_many

EXPERIENCE_LEVELS = [
    {"code": "entry", "label": "Entry-level", "description": "No prior professional experience required.", "sort_order": 1, "min_years": 0, "max_years": 1},
    {"code": "junior", "label": "Junior", "description": "Early-career, some professional experience.", "sort_order": 2, "min_years": 1, "max_years": 3},
    {"code": "mid", "label": "Mid-level", "description": "Solid independent contributor experience.", "sort_order": 3, "min_years": 3, "max_years": 6},
    {"code": "senior", "label": "Senior", "description": "Deep expertise, works independently on complex problems.", "sort_order": 4, "min_years": 6, "max_years": 10},
    {"code": "lead", "label": "Lead", "description": "Technical/functional leadership of a team or initiative.", "sort_order": 5, "min_years": 8, "max_years": 14},
    {"code": "principal", "label": "Principal/Staff", "description": "Organization-wide technical authority.", "sort_order": 6, "min_years": 12, "max_years": None},
    {"code": "executive", "label": "Executive/C-level", "description": "VP and above / C-suite roles.", "sort_order": 7, "min_years": 15, "max_years": None},
]


def seed_experience_levels(conn: Connection) -> SeedResult:
    return upsert_many(
        conn, schema="ref", table_name="experience_levels",
        rows=EXPERIENCE_LEVELS, conflict_cols=("code",),
    )