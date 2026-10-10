"""Fill the empty description-derived columns from the description text.

Fills five columns that every scraper left NULL because no board publishes them
as structured fields:

    core.job_descriptions.requirements
    core.job_descriptions.responsibilities
    core.job_descriptions.required_skills_text
    core.job_descriptions.preferred_skills_text
    core.job_descriptions.language_requirements_text

Measured before this script existed, all five were 0 of 112,781 rows filled
while 99.9% of ``description_clean`` was populated. The information was in the
description the whole time; it just had never been split out.

How
---
``normalization/section_extraction.py`` locates section headings inside the
flattened description and routes each section's list items into the matching
column. Headings survive the text cleaner even though newlines do not, so this
is a parse of existing data, not an inference.

Idempotent
----------
Only rows whose target columns are still NULL are selected, so re-running is a
no-op. ``--overwrite`` re-extracts rows that already have values, which is what
you want after improving the extractor.

Why a temp table rather than executemany
----------------------------------------
One set-based UPDATE per batch. 112k individual row updates over a WAN
connection to Neon would take hours; this takes minutes, and the local laptop
run is seconds.

Usage:
    python scripts/fill_description_sections.py --dry-run
    python scripts/fill_description_sections.py --dsn <local dsn>
    python scripts/fill_description_sections.py --limit 1000 --overwrite
"""

from __future__ import annotations

import argparse
import os
import sys

from loguru import logger
from sqlalchemy import text

#: Overridable via --dsn. A hardcoded DSN here once made a test write to the
#: live corpus, where the statements happened to match nothing -- but only by
#: luck. .env points DATABASE_URL at Neon, so a bare run would write to the
#: wrong database.
LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"

BATCH = 2000

#: The five derived columns, in the order they are reported.
COLUMNS = (
    "requirements",
    "responsibilities",
    "required_skills_text",
    "preferred_skills_text",
    "language_requirements_text",
)

#: Rows persist across the whole run (no ON COMMIT DROP) because each batch
#: reuses this table. It is a temp table, so it still disappears with the
#: session, and TRUNCATE is safe.
STAGE_DDL = """
CREATE TEMP TABLE IF NOT EXISTS section_stage (
    job_id                      bigint,
    requirements                text,
    responsibilities            text,
    required_skills_text        text,
    preferred_skills_text       text,
    language_requirements_text  text
)
"""

SECTION_UPDATE = """
UPDATE core.job_descriptions d
   SET requirements               = s.requirements,
       responsibilities           = s.responsibilities,
       required_skills_text       = s.required_skills_text,
       preferred_skills_text      = s.preferred_skills_text,
       language_requirements_text = s.language_requirements_text,
       updated_at                 = now()
  FROM section_stage s
 WHERE d.job_id = s.job_id
"""


def fetch_fill_rates(conn) -> dict[str, tuple[int, int]]:
    """Return {column: (filled, total)} for the five derived columns."""
    parts = ", ".join(
        f"count(*) FILTER (WHERE {c} IS NOT NULL AND btrim({c}) <> '') AS {c}" for c in COLUMNS
    )
    row = conn.execute(
        text(f"SELECT {parts}, count(*) FROM core.job_descriptions")  # noqa: S608
    ).one()
    total = row[-1]
    return {col: (row[i], total) for i, col in enumerate(COLUMNS)}


def print_rates(label: str, rates: dict[str, tuple[int, int]]) -> None:
    print(f"\n{'=' * 64}\n{label}\n{'=' * 64}")
    print(f"{'column':<30}{'filled':>12}{'empty':>12}{'pct':>9}")
    print("-" * 64)
    for col in COLUMNS:
        filled, total = rates[col]
        pct = 100 * filled / total if total else 0.0
        print(f"{col:<30}{filled:>12,}{total - filled:>12,}{pct:>8.1f}%")


def fetch_batch(conn, *, overwrite: bool, limit: int) -> list[tuple]:
    """Fetch one batch of rows that still need extraction.

    Selection differs by mode: normally a row qualifies only when ALL five
    columns are empty, because a partially-filled row means a previous run got
    interrupted and redoing it is harmless. With --overwrite, every row with a
    description is redone so the improved extractor can replace earlier output.
    """
    if overwrite:
        where = "WHERE d.description_clean IS NOT NULL"
    else:
        where = "WHERE d.description_clean IS NOT NULL AND " + " AND ".join(
            f"({c} IS NULL OR btrim({c}) = '')" for c in COLUMNS
        )
    return conn.execute(
        text(
            "SELECT d.job_id, d.description_clean FROM core.job_descriptions d "
            f"{where} ORDER BY d.job_id LIMIT :limit"
        ),
        {"limit": limit},
    ).all()


def select_candidate_ids(session, *, overwrite: bool, limit: int | None) -> list[int]:
    """Return every job_id that still needs extraction, ordered.

    Resolved ONCE up front and paged in Python afterwards. The selection
    predicate is expensive -- ``btrim()`` over five large text columns -- and
    re-running it per batch meant a full table scan per batch. That cost 38 full
    scans of 112,781 rows and the run did not finish in 50 minutes; the same
    work as a single scan plus cheap primary-key lookups finishes in minutes.
    """
    if overwrite:
        where = "WHERE description_clean IS NOT NULL"
    else:
        where = "WHERE description_clean IS NOT NULL AND " + " AND ".join(
            f"({c} IS NULL OR btrim({c}) = '')" for c in COLUMNS
        )
    rows = session.execute(
        text(f"SELECT job_id FROM core.job_descriptions {where} ORDER BY job_id")  # noqa: S608
    ).scalars().all()
    return list(rows[:limit]) if limit else list(rows)


def run_fill(
    session,
    *,
    extract,
    overwrite: bool,
    limit: int | None,
    batch_size: int,
) -> int:
    """Extract and write in batches until the selection runs dry.

    ``extract`` is passed in rather than imported here, so this function stays
    testable with a stub and the module-level import stays out of the way of
    --help.

    Returns the number of rows updated.
    """
    session.execute(text(STAGE_DDL))
    candidate_ids = select_candidate_ids(session, overwrite=overwrite, limit=limit)
    logger.info("{} rows selected for extraction", f"{len(candidate_ids):,}")

    total_updated = 0
    for start in range(0, len(candidate_ids), batch_size):
        chunk = candidate_ids[start : start + batch_size]
        batch = session.execute(
            text(
                "SELECT job_id, description_clean FROM core.job_descriptions "
                "WHERE job_id = ANY(:ids)"
            ),
            {"ids": chunk},
        ).all()

        payload = []
        for job_id, description in batch:
            result = extract(description or "")
            if not result.has_any:
                continue
            payload.append(
                {
                    "job_id": job_id,
                    "requirements": result.requirements,
                    "responsibilities": result.responsibilities,
                    "required_skills_text": result.required_skills_text,
                    "preferred_skills_text": result.preferred_skills_text,
                    "language_requirements_text": result.language_requirements_text,
                }
            )

        processed = start + len(batch)
        if payload:
            session.execute(text("TRUNCATE section_stage"))
            session.execute(
                text(
                    "INSERT INTO section_stage "
                    "(job_id, requirements, responsibilities, required_skills_text, "
                    " preferred_skills_text, language_requirements_text) "
                    "VALUES (:job_id, :requirements, :responsibilities, "
                    ":required_skills_text, :preferred_skills_text, "
                    ":language_requirements_text)"
                ),
                payload,
            )
            total_updated += session.execute(text(SECTION_UPDATE)).rowcount
        session.commit()
        logger.info(
            "processed {}/{} rows, {} updated so far",
            processed,
            len(candidate_ids),
            total_updated,
        )

    return total_updated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fill requirements/responsibilities/skills from description text"
    )
    parser.add_argument(
        "--dsn",
        help=(
            "Target database. Without this, DATABASE_URL is used, which .env "
            "points at NEON rather than the laptop."
        ),
    )
    parser.add_argument("--limit", type=int, help="Stop after N rows (testing).")
    parser.add_argument("--batch", type=int, default=BATCH, help="Rows per batch.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-extract rows that already have values.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report, but do not write.",
    )
    args = parser.parse_args()

    if args.dsn:
        os.environ["DATABASE_URL"] = args.dsn

    # Imported here so --help works without the normalization package loading.
    sys.path.insert(
        0,
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"),
    )
    from job_market_intel.db.session import get_session
    from job_market_intel.normalization.section_extraction import (
        extract_description_sections,
    )

    with get_session() as session:
        if args.dry_run:
            ids = select_candidate_ids(session, overwrite=args.overwrite, limit=args.limit or 1000)
            rows = session.execute(
                text(
                    "SELECT description_clean FROM core.job_descriptions "
                    "WHERE job_id = ANY(:ids)"
                ),
                {"ids": ids},
            ).all()
            hits = sum(
                1
                for (description,) in rows
                if extract_description_sections(description or "").has_any
            )
            print(f"\nDRY RUN over {len(rows):,} rows: {hits:,} would gain content.")
            print_rates("current state (unchanged)", fetch_fill_rates(session))
            return 0

        print_rates("BEFORE", fetch_fill_rates(session))
        total_updated = run_fill(
            session,
            extract=extract_description_sections,
            overwrite=args.overwrite,
            limit=args.limit,
            batch_size=args.batch,
        )
        print_rates("AFTER", fetch_fill_rates(session))
        print(f"\nrows updated: {total_updated:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
