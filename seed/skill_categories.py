"""Seeds ref.skill_categories — a flat (no parent used in v1) but
FK-ready hierarchy; parent_category_id is left NULL for all rows today
and is available for future subcategorization without a migration."""
from __future__ import annotations

from sqlalchemy import Connection

from .base import SeedResult, upsert_many

SKILL_CATEGORIES = [
    "Programming Language",
    "Framework",
    "Library",
    "Database",
    "Cloud Platform",
    "DevOps / Infrastructure Tool",
    "Operating System",
    "AI / ML",
    "Data & Analytics",
    "Design Tool",
    "Project Management Tool",
    "Certification",
    "Soft Skill",
    "Business Skill",
    "Other Tool",
    "Healthcare Skill",
    "Education Skill",
    "Retail & Hospitality Skill",
    "Construction & Trades Skill",
    "Manufacturing Skill",
    "Agriculture Skill",
    "Transport & Logistics Skill",
    "Government & Public Sector Skill",
    "Media & Arts Skill",
    "Beauty & Wellness Skill",
    "Banking & Finance Skill",
    "Business & Management Skill",
]


def seed_skill_categories(conn: Connection) -> SeedResult:
    rows = [{"category_name": name, "parent_category_id": None} for name in SKILL_CATEGORIES]
    return upsert_many(
        conn, schema="ref", table_name="skill_categories",
        rows=rows, conflict_cols=("category_name",),
    )
