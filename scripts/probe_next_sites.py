# Fix for akhtaboot_com.json:
# detail_json_path is only used for _embedded_detail_json and _next_data_detail_json
# When detail_json_url is used, the raw API response {"success": True, "job": {...}} 
# is passed directly to mapped_json_html WITHOUT extracting the "job" sub-object.
# 
# Fix: prefix all detail_json_map paths with "job." to navigate into the nested object
# Also remove detail_json_path since it doesn't apply here.

import json, pathlib

p = pathlib.Path("src/job_market_intel/scrapers/html_scraper/sites/akhtaboot_com.json")
cfg = json.loads(p.read_text(encoding="utf-8"))

# Remove detail_json_path (not applicable when detail_json_url is used)
cfg.pop("detail_json_path", None)

# Prefix map paths with "job."
cfg["detail_json_map"] = {
    "title": "job.title",
    "company": "job.company_name",
    "location": "job.location",
    "employment_type": "job.career_level",
    "description": "job.job_description",
    "posted_date": "job.created_at"
}

p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
print("Patched akhtaboot_com.json!")
print(json.dumps(cfg["detail_json_map"], indent=2))
