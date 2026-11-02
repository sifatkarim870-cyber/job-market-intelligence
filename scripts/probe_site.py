import urllib.request
import json

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def check_all_keys():
    url = "https://zimbojobs.com/api/jobs"
    req = urllib.request.Request(url, headers=headers)
    jobs = json.loads(urllib.request.urlopen(req, timeout=10).read()).get("jobs", [])
    all_keys = set()
    for j in jobs:
        all_keys.update(j.keys())
    print("All keys across all jobs in /api/jobs:", all_keys)

if __name__ == "__main__":
    check_all_keys()
