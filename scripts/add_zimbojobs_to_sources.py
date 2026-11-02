import json

path = "config/sources.json"
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

sources = data.get("sources", [])
# Check if already present
for s in sources:
    if s.get("code") == "zimbojobs_com":
        print("Already present!")
        break
else:
    new_entry = {
        "code": "zimbojobs_com",
        "group": "html",
        "script": "scripts/run_html_scraper.py",
        "timeout": 30,
        "max_env": "ZIMBOJOBS_COM_MAX_JOBS_PER_RUN",
        "enabled": True,
        "notes": "ZimboJobs Zimbabwe (zimbojobs.com) - Zimbabwe; Public Next.js API endpoints. Uses generic HTML scraper framework with JSON listing and detail endpoints. Registered 2026-11-03. listing_json_url=https://zimbojobs.com/api/jobs, detail_json_url=https://zimbojobs.com/api/vacancies/{id}. Verified 2026-11-03: 10/10 fetched, 10 parsed, 10 inserted, batch validation PASSED."
    }
    sources.append(new_entry)
    data["sources"] = sources
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("Added zimbojobs_com to config/sources.json!")
