"""
Seeds ref.sources. A source is marked is_active=True once its scraper is
built and verified (RemoteOK: Phase 2; We Work Remotely: Step 17;
Remotive: Step 18) — every source the roadmap names is pre-declared here
regardless of is_active so:
  (a) FK targets exist the moment a scraper module needs them,
  (b) `source_type` vocabulary is fixed up front,
  (c) enabling a new source in production is a one-row UPDATE, not a
      schema or seed-code change.
"""
from __future__ import annotations

from sqlalchemy import Connection

from .base import SeedResult, upsert_many

# (code, name, type, base_url, trust_score, is_active)
_SOURCES = [
    ("remoteok", "RemoteOK", "job_board", "https://remoteok.com", 0.75, True),
    ("weworkremotely", "We Work Remotely", "job_board", "https://weworkremotely.com", 0.75, True),
    ("remotive", "Remotive", "job_board", "https://remotive.com", 0.70, True),
    ("indeed", "Indeed", "aggregator", "https://indeed.com", 0.80, False),
    ("linkedin", "LinkedIn", "job_board", "https://linkedin.com", 0.85, False),
    ("glassdoor", "Glassdoor", "job_board", "https://glassdoor.com", 0.75, False),
    ("govt_portal", "Government Job Portals", "government", None, 0.90, False),
    ("company_career_page", "Company Career Pages", "company_career_page", None, 0.85, False),
]


def seed_sources(conn: Connection) -> SeedResult:
    rows = [
        {
            "source_code": code,
            "source_name": name,
            "source_type": stype,
            "base_url": url,
            "requires_auth": False,
            "terms_of_service_url": None,
            "trust_score": trust,
            "is_active": active,
        }
        for code, name, stype, url, trust, active in _SOURCES
    ]
    # update_cols excludes is_active on purpose: once ops flips a source
    # live in prod, re-running the seed must never silently deactivate it.
    return upsert_many(
        conn, schema="ref", table_name="sources", rows=rows,
        conflict_cols=("source_code",),
        update_cols=["source_name", "source_type", "base_url", "trust_score"],
    )
