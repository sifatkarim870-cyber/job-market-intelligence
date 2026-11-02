import requests
import json

headers = {"User-Agent": "Mozilla/5.0"}
resp = requests.get("https://zimbojobs.com/api/jobs", headers=headers)
data = resp.json()
print("Success:", data.get("success"))
jobs = data.get("jobs", [])
print(f"Total jobs in listing: {len(jobs)}")

if jobs:
    sample = jobs[0]
    print("Listing job keys:", list(sample.keys()))
    print("Sample job summary:")
    for k in ["_id", "title", "company", "location", "salary", "jobType", "createdAt", "expiryDate", "category"]:
        print(f"  {k}: {sample.get(k)}")

    # Check detail API
    job_id = sample["_id"]
    d_resp = requests.get(f"https://zimbojobs.com/api/jobs/{job_id}", headers=headers)
    d_data = d_resp.json()
    print("\nDetail API keys:", list(d_data.keys()))
    for k in ["jobTitle", "companyName", "jobDescription", "jobRequirements", "location", "salary", "jobType", "employmentType", "education", "experience"]:
        print(f"  {k}: {str(d_data.get(k))[:100]}")
