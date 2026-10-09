"""Probe candidate FREE job APIs to see which actually respond, and with what.

Do not write scrapers against endpoints that are dead, key-gated, or blocked.
This hits each candidate once, records the outcome, and prints the first
record's field names, so the build is driven by what actually works rather
than by what the docs claim.

Uses the project's own ``common.http_client.fetch_json`` -- the same call path
every scraper uses -- so a probe that passes here is one a scraper can make.
A status of 200 with unparseable JSON is still a failure for our purposes.

Run:  uv run python scripts/probe_free_apis.py
"""

from __future__ import annotations

import json
import time

from job_market_intel.common.http_client import (
    HTTPClientError,
    PermanentHTTPError,
    TransientHTTPError,
    fetch_json,
)

#: (label, url, path-to-list, path-inside-to-first-dict)
CANDIDATES: list[tuple[str, str, tuple[str, ...]]] = [
    # ---- job-board / aggregator APIs, no key --------------------------
    ("arbeitnow", "https://www.arbeitnow.com/api/job-board-api", ("data",)),
    ("himalayas", "https://himalayas.app/jobs/api?limit=3", ("jobs",)),
    ("jobicy", "https://jobicy.com/api/v2/remote-jobs?count=3", ("jobs",)),
    ("themuse", "https://www.themuse.com/api/public/jobs?page=1", ()),
    ("remotive", "https://remotive.com/api/remote-jobs?limit=3", ("jobs",)),
    ("remoteok", "https://remoteok.com/api", ()),
    ("nofluffjobs", "https://nofluffjobs.com/api/search/posting?criteria="
                    "&page=1&sortBy=published&orderBy=DESC", ("postings",)),
    ("justjoin", "https://justjoin.it/api/offers", ("offers",)),
    ("djinni", "https://djinni.co/api/v2/user-posts?no_auth=true&type=all"
               "&limit=3", ("posts",)),
    ("remotive_rss", "https://remotive.com/api/remote-jobs?limit=3", ("jobs",)),

    # ---- ATS public boards: the high-leverage family ------------------
    ("greenhouse_gitlab", "https://boards-api.greenhouse.io/v1/boards/gitlab/jobs", ("jobs",)),
    ("greenhouse_stripe", "https://boards-api.greenhouse.io/v1/boards/stripe/jobs", ("jobs",)),
    ("greenhouse_datadog", "https://boards-api.greenhouse.io/v1/boards/datadog/jobs", ("jobs",)),
    ("greenhouse_reddit", "https://boards-api.greenhouse.io/v1/boards/reddit/jobs", ("jobs",)),
    ("lever_netflix", "https://api.lever.co/v0/postings/netflix?mode=json", ("data",)),
    ("lever_shopify", "https://api.lever.co/v0/postings/shopify?mode=json", ("data",)),
    ("lever_plaid", "https://api.lever.co/v0/postings/plaid?mode=json", ("data",)),
    ("ashby_railway", "https://api.ashbyhq.com/posting-api/job-board/railway", ("jobs",)),
    ("workable_elcom", "https://apply.workable.com/api/v1/widget/accounts/elcom"
                       "?details=true", ("jobs",)),
    ("smartrecruiters_bosch", "https://api.smartrecruiters.com/v1/companies/"
                              "BoschGroup/postings?limit=3", ("content",)),
    ("recruitee_ing", "https://ing.recruitee.com/api/offers/", ("offers",)),
    ("breezy_linear", "https://breezy.hr/json/linear", ()),
    ("teamtailor_deel", "https://api.teamtailor.com/jobs/deel?version=v2", ("jobs",)),
    ("jobstreet_au", "https://jobstreet.com.au/api/challenge-search", ()),
]


def dig(payload: object, path: tuple[str, ...]) -> tuple[dict | None, int | None]:
    """Follow `path`, then auto-detect the list, return (first record, length)."""
    node = payload
    for key in path:
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            node = None
            break
    if node is None and isinstance(payload, dict):
        node = payload
    if isinstance(node, dict):
        for key in ("data", "jobs", "posts", "offers", "postings", "content",
                    "results", "list"):
            if isinstance(node.get(key), list):
                node = node[key]
                break
        else:
            return None, None
    if isinstance(node, list):
        return (node[0] if node and isinstance(node[0], dict) else None), len(node)
    return None, None


def main() -> int:
    rows: list[dict] = []
    for label, url, path in CANDIDATES:
        entry: dict = {"label": label, "url": url}
        t0 = time.time()
        try:
            payload = fetch_json(url, timeout_seconds=25.0)
            entry["ms"] = int((time.time() - t0) * 1000)
            rec, n = dig(payload, path)
            entry["n"] = n
            entry["fields"] = sorted(rec.keys()) if rec else None
            entry["ok"] = bool(rec)
        except PermanentHTTPError as exc:
            entry["ok"] = False
            entry["err"] = f"HTTP {exc}"[:110]
        except (TransientHTTPError, HTTPClientError) as exc:
            entry["ok"] = False
            entry["err"] = f"{type(exc).__name__}: {str(exc)[:90]}"
        except Exception as exc:  # noqa: BLE001 - probing many hosts
            entry["ok"] = False
            entry["err"] = f"{type(exc).__name__}: {str(exc)[:90]}"
        rows.append(entry)
        time.sleep(0.4)          # be polite; these are third-party servers

    print(f"{'label':<22}{'ms':>6}  n      first fields")
    print("-" * 116)
    for e in rows:
        fields = ", ".join(e.get("fields") or []) or e.get("err", "")
        print(f"{e['label']:<22}{str(e.get('ms', '-')):>6}  {str(e.get('n', '-')):<6}{fields[:74]}")

    ok = [e for e in rows if e["ok"]]
    print(f"\n=== {len(ok)}/{len(rows)} usable (JSON, first record has fields) ===")
    for e in ok:
        print(f"   {e['label']:<22} n={e['n']}")
    (Path(__file__).resolve().parent / "probe_free_apis_result.json").write_text(
        json.dumps(rows, indent=2, default=str), encoding="utf-8")
    print("\nwrote scripts/probe_free_apis_result.json")
    return 0


from pathlib import Path  # noqa: E402  (used only for the result dump)

if __name__ == "__main__":
    raise SystemExit(main())