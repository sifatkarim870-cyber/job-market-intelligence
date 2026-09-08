"""Interactive human review of pending company-alias candidates (Step 25).

``scripts/run_company_resolution_batch.py`` writes proposed aliases to
``core.company_aliases`` but never confirms them -- confirmed design
decision: ``core.companies.is_verified`` stays FALSE until a human
approves. This script is that human-in-the-loop step.

"Pending" is defined as: a canonical company (``core.companies.is_verified
= FALSE``) that has at least one ``core.company_aliases`` row pointing at
it with ``source_id IS NULL`` (i.e. produced by the batch job, not by a
scraper encountering a name variant directly). Once you approve a
company's alias group, ``core.companies.is_verified`` flips to TRUE and
it won't show up again on a future run of this script or the batch job
(the batch job's own idempotency check is separate -- see
``normalization/company_resolution.py``).

This script never merges companies or changes ``core.jobs.company_id``.
Approve only confirms "yes, these are genuinely the same employer" as a
record for future use (e.g. a future, separate merge step you'd design
later); reject deletes the specific candidate rows AND logs the
rejection (via ``normalization.company_resolution.reject_alias_candidates``)
so the batch job won't re-propose the identical pair next run -- a real
bug found during first real use: rejecting used to only delete the
alias row, which meant the very next batch run had nothing left to
recognize the pair as already-seen and proposed it right back. Skip
leaves everything untouched for next time.

Usage:
    python scripts/review_company_aliases.py
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from job_market_intel.common.config import get_settings
from job_market_intel.common.logger import configure_logging
from job_market_intel.db.session import get_session
from job_market_intel.normalization.company_resolution import reject_alias_candidates


def _fetch_pending_groups(session: Session) -> list[dict]:
    """One row per pending canonical company, with its candidate aliases
    aggregated into a list -- so the reviewer sees a whole alias group
    (a canonical company plus every proposed variant of it) at once,
    not one alias row at a time.
    """
    rows = session.execute(
        text(
            "SELECT "
            "  c.company_id, c.company_name, "
            "  array_agg(ca.alias_id ORDER BY ca.alias_id) AS alias_ids, "
            "  array_agg(ca.raw_name ORDER BY ca.alias_id) AS raw_names, "
            "  array_agg(ca.match_confidence ORDER BY ca.alias_id) AS confidences "
            "FROM core.companies c "
            "JOIN core.company_aliases ca "
            "  ON ca.company_id = c.company_id AND ca.source_id IS NULL "
            "WHERE c.is_verified = FALSE "
            "GROUP BY c.company_id, c.company_name "
            "ORDER BY c.company_name"
        )
    ).all()

    return [
        {
            "company_id": row.company_id,
            "company_name": row.company_name,
            "alias_ids": row.alias_ids,
            "raw_names": row.raw_names,
            "confidences": row.confidences,
        }
        for row in rows
    ]


def _approve(session: Session, company_id: int) -> None:
    session.execute(
        text("UPDATE core.companies SET is_verified = TRUE WHERE company_id = :company_id"),
        {"company_id": company_id},
    )


def main() -> int:
    settings = get_settings()
    configure_logging(log_dir="logs", console_level=settings.log_level, file_level="DEBUG")

    with get_session() as session:
        groups = _fetch_pending_groups(session)

        if not groups:
            print("No pending company-alias candidates to review.")
            return 0

        print(f"{len(groups)} canonical company/companies with pending candidates:\n")

        approved = 0
        rejected = 0
        skipped = 0

        for group in groups:
            print("-" * 70)
            print(f"Canonical: {group['company_name']} (company_id={group['company_id']})")
            print("Candidate alias(es):")
            for raw_name, confidence in zip(group["raw_names"], group["confidences"], strict=True):
                print(f"  - '{raw_name}' (match_confidence={confidence})")

            choice = input("\n[a]pprove / [r]eject / [s]kip / [q]uit? ").strip().lower()

            if choice == "a":
                _approve(session, group["company_id"])
                approved += 1
                print(f"Approved: {group['company_name']} is now is_verified = TRUE.\n")
            elif choice == "r":
                count = reject_alias_candidates(
                    session,
                    canonical_company_id=group["company_id"],
                    canonical_company_name=group["company_name"],
                    alias_raw_names=group["raw_names"],
                )
                rejected += 1
                print(
                    f"Rejected: {count} candidate alias row(s) deleted "
                    "(logged, won't be re-proposed).\n"
                )
            elif choice == "q":
                print("Quitting review session.\n")
                break
            else:
                skipped += 1
                print("Skipped.\n")

    print("=" * 70)
    print(f"Approved: {approved}  Rejected: {rejected}  Skipped: {skipped}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
