"""Probe failing HTML scraper sites: HTTP status, size, link counts, candidate paths.

Usage:
    uv run python scripts/probe_failing_sites.py                # every non-OK source
    uv run python scripts/probe_failing_sites.py --only cv_lt --only fne_cm
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from job_market_intel.scrapers.html_scraper.client import _extract_links_from_html

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / "src" / "job_market_intel" / "scrapers" / "html_scraper" / "sites"
RESULTS = ROOT / "reports" / "html_scraper_test_results.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)

CANDIDATE_PATHS = [
    "/jobs",
    "/job",
    "/careers",
    "/career",
    "/vacancies",
    "/vacancy",
    "/job-search",
    "/search",
    "/jobs/search",
    "/en/jobs",
    "/emplois",
    "/offres-emploi",
    "/offres-d-emploi",
    "/empleos",
    "/empleo",
    "/bolsa-de-empleo",
    "/trabajos",
    "/ofertas-de-trabajo",
    "/vagas",
    "/vagas-emprego",
    "/empregos",
    "/praca",
    "/prace",
    "/nabidky",
    "/stellen",
    "/stellenangebote",
    "/jobs-in",
    "/lavoro",
    "/offerte-di-lavoro",
    "/vacatures",
    "/ofertas",
    "/anuncios",
    "/arbs",
    "/darba",
    "/darbo",
    "/trabajo",
    "/jobs/all",
    "/vacancies/all",
    "/",
]


def discover_candidates(base: str, timeout: int = 20, limit: int = 12) -> list[str]:
    """Find job-ish paths linked from the site's own homepage."""
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    try:
        r = session.get(base, timeout=timeout)
    except requests.RequestException:
        return []
    soup = BeautifulSoup(r.text or "", "html.parser")
    paths: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        full = urljoin(r.url, a["href"])
        if not full.startswith(base):
            continue
        path = re.sub(r"^https?://[^/]+", "", full).split("?")[0].rstrip("/") or "/"
        if path in seen:
            continue
        low = path.lower()
        if any(
            kw in low
            for kw in (
                "job",
                "career",
                "vacan",
                "emploi",
                "empleo",
                "trabajo",
                "praca",
                "prace",
                "stelle",
                "lavoro",
                "vacature",
                "vaga",
                "ofert",
                "annunci",
                "stellen",
                "arbs",
                "darb",
                "allas",
                "posao",
                "zaposl",
            )
        ):
            seen.add(path)
            paths.append(path)
        if len(paths) >= limit:
            break
    return paths


def probe(url: str, timeout: int = 20) -> dict:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        return {"url": url, "error": type(exc).__name__ + ": " + str(exc)[:120]}
    html = r.text or ""
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.find_all("a", href=True)
    job_links = _extract_links_from_html(html, url)
    title = soup.title.get_text(strip=True)[:80] if soup.title else ""
    return {
        "url": url,
        "status": r.status_code,
        "final_url": r.url,
        "bytes": len(html),
        "anchors": len(anchors),
        "job_links": len(job_links),
        "sample": [u for u, _ in job_links[:3]],
        "title": title,
        "server": r.headers.get("server", "")[:40],
        "cf": "cloudflare" in (r.headers.get("server", "") + html[:2000]).lower(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=None)
    ap.add_argument("--try-paths", action="store_true", help="Probe candidate listing paths")
    ap.add_argument("--max-candidates", type=int, default=40)
    args = ap.parse_args()

    if args.only:
        codes = args.only
    else:
        rows = json.loads(RESULTS.read_text(encoding="utf-8"))
        codes = [r["code"] for r in rows if r["status"] != "OK"]

    for code in codes:
        cfg = json.loads((SITES / f"{code}.json").read_text(encoding="utf-8"))
        base = cfg["base_url"].rstrip("/")
        path = cfg.get("listing_path") or "/"
        url = base + path
        res = probe(url)
        print(f"\n=== {code} ===")
        print(json.dumps(res, indent=2, ensure_ascii=False))
        if args.try_paths and res.get("job_links", 0) == 0:
            hits = []
            seen_paths = {path}
            for cand in discover_candidates(base) + CANDIDATE_PATHS[: args.max_candidates]:
                if cand in seen_paths:
                    continue
                seen_paths.add(cand)
                r = probe(base + cand, timeout=15)
                if r.get("job_links", 0) > 0:
                    hits.append((cand, r["status"], r["job_links"], r.get("final_url")))
            hits.sort(key=lambda x: -x[2])
            print("candidate paths with job links:")
            for hit in hits[:8]:
                print(f"   {hit}")
            if not hits:
                print("   none of the candidate paths produced job links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
