"""Retire the duplicate source codes the generated configs introduced.

The 118 auto-generated site configs were registered under new codes without
checking whether a scraper already covered the same board. After backfilling
``ref.sources.base_url`` from the configs, 22 hosts had two codes. Two codes for
one board means every posting is stored twice under two source_ids --
``hellojob`` and ``hellojob_az`` held the same 14 postings with the same
``source_job_id`` and title.

This script keeps one code per host and retires the other:

* deletes the redundant code's rows from core.jobs (they are exact copies),
* sets ``ref.sources.is_active = false`` (audit trail kept, not dropped),
* deletes the redundant site config,
* removes the redundant entry from config/sources.json.

Run:  uv run python scripts/retire_duplicate_sources.py --dry-run
      uv run python scripts/retire_duplicate_sources.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text

from job_market_intel.db.session import get_session
from job_market_intel.db.transaction import transaction

ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / "src" / "job_market_intel" / "scrapers" / "html_scraper" / "sites"
SOURCES = ROOT / "config" / "sources.json"

#: redundant code -> canonical code that already covers the same host
RETIRE = {
    "acbar_org": "acbar_jobs",
    "angolaemprego_com": "angola_emprego",
    "careerjunction_co_za": "careerjunction",
    "corporatestaffing_co_ke": "corporatestaffing_ke",
    "fijisun_com_fj": "fijisun_jobs",
    "jobsireland_ie": "jobsireland",
    "jobsnepal_com": "jobsnepal",
    "jobwebghana_com": "jobwebghana",
    "mustakbil_com": "mustakbil",
    "philjobnet_gov_ph": "philjobnet",
    "shine_com": "shine",
    "hiiraan_com": "hiiraan_jobs",
    "agenceemploijeunes_ci": "agenceemploijeunes",
    "alwatwan_net": "alwatwan",
    "alwihdainfo_com": "alwihdainfo",
    "educarriere_ci": "educarriere",
    "ethiojobs_net": "ethiojobs",
    "fnecm": "fne_cm",
    "hellojob_az": "hellojob",
    "hotnigerianjobs_com": "hotnigerianjobs",
    "jobzella_com": "jobzella",
    "minajobs_net": "minajobs",
    "prace_cz": "pracecz",
    "skill_jobs": "skilljobs",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = json.loads(SOURCES.read_text(encoding="utf-8"))
    entries = {e["code"]: e for e in data["sources"]}

    with get_session() as session:
        counts = dict(
            session.execute(
                text(
                    "SELECT s.source_code, count(j.job_id) FROM ref.sources s "
                    "LEFT JOIN core.jobs j ON j.source_id = s.source_id "
                    "GROUP BY s.source_code"
                )
            ).all()
        )
        for redundant, canonical in RETIRE.items():
            if redundant not in counts:
                print(f"skip {redundant}: not in registry")
                continue
            print(
                f"{redundant} -> {canonical}: {counts[redundant]} row(s) to delete, "
                f"config={'yes' if (SITES / f'{redundant}.json').exists() else 'no'}, "
                f"sources.json={'yes' if redundant in entries else 'no'}"
            )

        if args.dry_run:
            return 0

        with transaction(session):
            for redundant in RETIRE:
                if redundant not in counts:
                    continue
                session.execute(
                    text(
                        "DELETE FROM core.jobs WHERE source_id = "
                        "(SELECT source_id FROM ref.sources WHERE source_code = :code)"
                    ),
                    {"code": redundant},
                )
                session.execute(
                    text(
                        "UPDATE ref.sources SET is_active = false, updated_at = now() "
                        "WHERE source_code = :code"
                    ),
                    {"code": redundant},
                )
            session.commit()

    retired = 0
    for redundant, _canonical in RETIRE.items():
        cfg = SITES / f"{redundant}.json"
        if cfg.exists():
            cfg.unlink()
            retired += 1
    data["sources"] = [e for e in data["sources"] if e["code"] not in RETIRE]
    SOURCES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"deleted {retired} config(s); sources.json now {len(data['sources'])} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
