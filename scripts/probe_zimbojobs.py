import requests
from bs4 import BeautifulSoup

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

url = "https://zimbojobs.com/jobs/6ae8b67ef7ac94076435b37d"
resp = requests.get(url, headers=headers, timeout=15)
soup = BeautifulSoup(resp.text, "html.parser")
for i, s in enumerate(soup.find_all("script")):
    t = s.get_text()
    if len(t) > 500:
        print(f"\n--- Script {i} ({len(t)} chars) ---")
        print(t[:600])
