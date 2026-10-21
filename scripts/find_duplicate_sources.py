"""Find registry rows that point at the same site under different source codes.

Two codes for one board mean every posting is stored twice under two source_ids.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text

from job_market_intel.db.session import get_session

SITES = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "job_market_intel"
    / "scrapers"
    / "html_scraper"
    / "sites"
)


def host(url: str) -> str:
    if not url:
        return ""
    h = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


with get_session() as s:
    rows = s.execute(
        text(
            "SELECT s.source_code, s.base_url, s.is_active, count(j.job_id) "
            "FROM ref.sources s LEFT JOIN core.jobs j ON j.source_id = s.source_id "
            "GROUP BY s.source_code, s.base_url, s.is_active ORDER BY s.source_code"
        )
    ).all()

configs = {p.stem for p in SITES.glob("*.json")}
by_host: dict[str, list[tuple]] = defaultdict(list)
for code, url, active, jobs in rows:
    h = host(url or "")
    if h:
        by_host[h].append((code, active, int(jobs), code in configs))

print("hosts with more than one source code:\n")
for h, entries in sorted(by_host.items()):
    if len(entries) < 2:
        continue
    print(f"{h}")
    for code, active, jobs, has_cfg in sorted(entries, key=lambda e: -e[2]):
        print(f"   {code:32} active={str(active):5} rows={jobs:6} config={has_cfg}")
    print()
