"""Seeds ref.remote_work_types — five states covering how a posting relates
to a physical location, matching ref.locations' remote_work_type_id FK."""
from __future__ import annotations

from sqlalchemy import Connection

from .base import SeedResult, upsert_many

REMOTE_WORK_TYPES = [
    {"code": "on_site", "label": "On-site", "description": "Work is performed at a fixed employer location.", "sort_order": 1},
    {"code": "hybrid", "label": "Hybrid", "description": "Mix of on-site and remote work at a specific location.", "sort_order": 2},
    {"code": "remote_city", "label": "Remote (City-restricted)", "description": "Remote, but candidate must reside in/near a specific city.", "sort_order": 3},
    {"code": "remote_country", "label": "Remote (Country-restricted)", "description": "Remote within a specific country only.", "sort_order": 4},
    {"code": "remote_region", "label": "Remote (Region-restricted)", "description": "Remote within a multi-country region (e.g. EU, LATAM, APAC).", "sort_order": 5},
    {"code": "remote_global", "label": "Remote (Global)", "description": "Remote from anywhere in the world.", "sort_order": 6},
]


def seed_remote_work_types(conn: Connection) -> SeedResult:
    return upsert_many(
        conn, schema="ref", table_name="remote_work_types",
        rows=REMOTE_WORK_TYPES, conflict_cols=("code",),
    )