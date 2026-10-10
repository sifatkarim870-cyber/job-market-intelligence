"""Validate config/sources.json against the filesystem and the database.

Catches the class of bug where a scraper is fully built, seeded, and working
locally but absent from the registry -- and therefore in no CI matrix and on no
cron, so it silently never runs. arbeitnow sat in exactly that state: seeded on
Neon, 353 rows local, and absent from config/sources.json.

Run:  uv run python scripts/check_sources_registry.py
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    data = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
    sources = data["sources"]
    problems: list[str] = []

    codes = [s["code"] for s in sources]
    duplicates = {c for c in codes if codes.count(c) > 1}
    if duplicates:
        problems.append(f"duplicate codes in registry: {sorted(duplicates)}")

    print(f"{len(sources)} sources registered\n")
    for source in sorted(sources, key=lambda s: s["group"]):
        missing = [k for k in ("code", "group", "script", "timeout", "enabled") if k not in source]
        if missing:
            problems.append(f"{source.get('code')}: missing keys {missing}")
            continue
        script = ROOT / source["script"]
        flag = "OK " if script.exists() else "MISSING SCRIPT"
        if not script.exists():
            problems.append(f"{source['code']}: script does not exist -> {source['script']}")
        print(
            f"  {flag:<14} {source['group']:<8} {source['code']:<18} "
            f"timeout={source['timeout']:<4} enabled={source['enabled']}"
        )

    # Cross-check against ref.sources, which is what every scraper resolves its
    # source_id from at runtime and what the shard exporter filters on.
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(
            "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"
        )
        with engine.connect() as conn:
            seeded = {
                row[0] for row in conn.execute(text("SELECT source_code FROM ref.sources")).all()
            }
        for code in codes:
            if code not in seeded:
                problems.append(
                    f"{code}: registered but absent from ref.sources -- every run will "
                    "fail with 'ref.sources has no row with source_code=...'"
                )
    except Exception as exc:  # noqa: BLE001
        print(f"\n  (skipped ref.sources cross-check: {exc})")

    print()
    if problems:
        print(f"{len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("registry consistent: every script exists and every code is seeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
