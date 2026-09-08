"""Seeds ref.education_levels with ordinal_rank for sortability."""

from __future__ import annotations

from sqlalchemy import Connection

from .base import SeedResult, upsert_many

EDUCATION_LEVELS = [
    {"code": "none", "label": "No formal requirement", "description": None, "ordinal_rank": 0},
    {"code": "high_school", "label": "High School Diploma", "description": None, "ordinal_rank": 1},
    {"code": "associate", "label": "Associate Degree", "description": None, "ordinal_rank": 2},
    {"code": "bachelor", "label": "Bachelor's Degree", "description": None, "ordinal_rank": 3},
    {"code": "master", "label": "Master's Degree", "description": None, "ordinal_rank": 4},
    {"code": "phd", "label": "PhD / Doctorate", "description": None, "ordinal_rank": 5},
    {
        "code": "professional_certification",
        "label": "Professional Certification",
        "description": "Vocational/industry certification in lieu of a degree.",
        "ordinal_rank": 3,
    },
]


def seed_education_levels(conn: Connection) -> SeedResult:
    return upsert_many(
        conn,
        schema="ref",
        table_name="education_levels",
        rows=EDUCATION_LEVELS,
        conflict_cols=("code",),
    )
