"""Generic browser (Selenium) scraper framework.

For boards whose job listings are rendered client-side: a plain HTTP request
gets an empty shell, a real Chrome gets the list. One JSON file per site, no
per-site Python.

Config format (scrapers/browser_scraper/sites/<code>.json):
    {
        "source_code": "ethiojobs",
        "source_name": "Ethiojobs",
        "country": "Ethiopia",
        "base_url": "https://ethiojobs.com",
        "listing_path": "/",
        "listing_pagination": "?page={page}",
        "max_pages": 5,
        "max_jobs_per_run": 40,
        "listing_ready_selector": "[data-cy='job-list']",
        "listing_wait_seconds": 15,
        "selectors": {
            "job_link": "a[href*='/jobs/']",
            "job_title": "h2, h3",
            "description": ".job-description, [class*='description']"
        }
    }
"""

from job_market_intel.scrapers.browser_scraper.config import (
    BrowserScraperSettings,
    BrowserSiteConfig,
    list_available_browser_sites,
    load_browser_site_config,
)
from job_market_intel.scrapers.browser_scraper.pipeline import BrowserScraperPipeline

__all__ = [
    "BrowserScraperPipeline",
    "BrowserScraperSettings",
    "BrowserSiteConfig",
    "list_available_browser_sites",
    "load_browser_site_config",
]
