"""
CLI entrypoint: `python -m seed.run_all`

Runs every seed module, in FK-safe dependency order, inside one
transaction. On success prints a summary report; on any failure, the
entire run rolls back (nothing partially seeded), and the exception is
re-raised with a non-zero exit code for CI.
"""
from __future__ import annotations

import sys

from .auth import seed_admin_user, seed_roles
from .benefits import seed_benefits
from .cities import seed_cities
from .countries import seed_countries
from .currencies import seed_currencies
from .db import seed_connection
from .education_levels import seed_education_levels
from .employment_types import seed_employment_types
from .experience_levels import seed_experience_levels
from .job_categories import seed_job_categories
from .languages import seed_languages
from .regions import seed_regions
from .remote_work_types import seed_remote_work_types
from .skill_categories import seed_skill_categories
from .skills import seed_skills
from .sources import seed_sources
from .utils import get_logger

logger = get_logger("run_all")

# Order matters — see README "Execution Dependency Graph".
SEED_STEPS = [
    ("currencies", seed_currencies),
    ("countries", seed_countries),
    ("regions", seed_regions),
    ("cities", seed_cities),
    ("remote_work_types", seed_remote_work_types),
    ("employment_types", seed_employment_types),
    ("experience_levels", seed_experience_levels),
    ("education_levels", seed_education_levels),
    ("job_categories", seed_job_categories),
    ("skill_categories", seed_skill_categories),
    ("skills", seed_skills),
    ("benefits", seed_benefits),
    ("languages", seed_languages),
    ("sources", seed_sources),
    ("auth.roles", seed_roles),
    ("auth.admin_user", seed_admin_user),
]


def run_all() -> int:
    logger.info("Starting reference-data seed run (%d steps)...", len(SEED_STEPS))
    results = []
    try:
        with seed_connection() as conn:
            for name, fn in SEED_STEPS:
                logger.info("Seeding: %s", name)
                res = fn(conn)
                results.append(res)
                logger.info(str(res))
    except Exception:
        logger.exception("Seed run FAILED — transaction rolled back, no partial writes committed.")
        return 1

    total_inserted = sum(r.inserted for r in results)
    total_updated = sum(r.updated for r in results)
    total_unchanged = sum(r.unchanged for r in results)
    logger.info(
        "Seed run complete. inserted=%d updated=%d unchanged=%d across %d tables.",
        total_inserted, total_updated, total_unchanged, len(results),
    )
    return 0


if __name__ == "__main__":
    sys.exit(run_all())