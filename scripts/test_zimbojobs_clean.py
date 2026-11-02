import urllib.request
import json
from datetime import date
from job_market_intel.scrapers.html_scraper.models import RawHtmlScraperJob
from job_market_intel.cleaning.html_scraper_cleaner import HtmlScraperCleaner

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def test_cleaner():
    url = "https://zimbojobs.com/api/vacancies/6ae8b67ef7ac94076435b37d"
    v = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10).read())
    
    raw_job = RawHtmlScraperJob(
        source_code="zimbojobs_com",
        source_job_id=v["_id"],
        title=v["title"],
        company_name="ZimboJobs",
        location=v["location"],
        description=v["description"],
        url=f"https://zimbojobs.com/jobs/{v['_id']}",
        country="Zimbabwe",
        posted_date=date.today(),
    )
    
    cleaner = HtmlScraperCleaner(currency_iso_code="USD", pay_period="monthly")
    cleaned = cleaner.clean_job(raw_job)
    for k in ["job_title_raw", "company_name", "location_raw", "country_code", "education_level_code", "experience_level_code", "remote_work_type_code", "job_category_code"]:
        print(f"  {k}: {getattr(cleaned, k, None)}")

if __name__ == "__main__":
    test_cleaner()
