import json

path = "config/sources.json"
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

sources = data.get("sources", [])
for s in sources:
    if s.get("code") == "akhtaboot_com":
        print("Already present!")
        break
else:
    new_entry = {
        "code": "akhtaboot_com",
        "group": "html",
        "script": "scripts/run_html_scraper.py",
        "timeout": 30,
        "max_env": "AKHTABOOT_COM_MAX_JOBS_PER_RUN",
        "enabled": True,
        "notes": "Akhtaboot (akhtaboot.com) - Jordan/Middle East; Public REST API. listing_json_url=https://www.akhtaboot.com/api/v1/jobs, detail_json_url=https://www.akhtaboot.com/api/v1/jobs/{id}, detail_json_map keys nested under 'job.*'. Registered 2026-11-03. Verified 2026-11-03: 10/10 fetched, 10 parsed, 10 inserted, batch validation PASSED."
    }
    sources.append(new_entry)
    data["sources"] = sources
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("Added akhtaboot_com to config/sources.json!")
