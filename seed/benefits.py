"""Seeds ref.benefits."""
from __future__ import annotations

from sqlalchemy import Connection

from .base import SeedResult, upsert_many

# (name, category, description)
_BENEFITS = [
    ("Health Insurance", "health", None),
    ("Dental Insurance", "health", None),
    ("Vision Insurance", "health", None),
    ("Mental Health Support", "health", None),
    ("Life Insurance", "health", None),
    ("Disability Insurance", "health", None),
    ("401(k) / Retirement Plan", "financial", None),
    ("401(k) Matching", "financial", None),
    ("Stock Options / Equity", "financial", None),
    ("Performance Bonus", "financial", None),
    ("Referral Bonus", "financial", None),
    ("Relocation Assistance", "financial", None),
    ("Tuition Reimbursement", "financial", None),
    ("Paid Time Off (PTO)", "time-off", None),
    ("Unlimited PTO", "time-off", None),
    ("Paid Parental Leave", "time-off", None),
    ("Paid Sick Leave", "time-off", None),
    ("Paid Holidays", "time-off", None),
    ("Sabbatical Leave", "time-off", None),
    ("Remote Work Stipend", "perks", None),
    ("Home Office Setup", "perks", None),
    ("Gym Membership", "perks", None),
    ("Free Meals / Snacks", "perks", None),
    ("Commuter Benefits", "perks", None),
    ("Pet-friendly Office", "perks", None),
    ("Company Retreats", "perks", None),
    ("Flexible Working Hours", "perks", None),
    ("Employee Discount Program", "perks", None),
    ("Visa Sponsorship", "other", None),
    ("Childcare Support", "other", None),
    ("Professional Development Budget", "other", None),
]


def seed_benefits(conn: Connection) -> SeedResult:
    rows = [
        {"benefit_name": name, "benefit_category": category, "description": desc}
        for name, category, desc in _BENEFITS
    ]
    return upsert_many(
        conn, schema="ref", table_name="benefits",
        rows=rows, conflict_cols=("benefit_name",),
    )
