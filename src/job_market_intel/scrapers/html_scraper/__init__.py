"""Generic HTML scraper framework for HTML_SCRAPER category sites.

Each site is configured via a JSON file with CSS selectors. No custom Python
needed per site -- just drop a config file in scrapers/html_scraper/sites/.

Config format:
{
    "source_code": "skilljobs",
    "source_name": "Skill.jobs",
    "country": "Bangladesh",
    "base_url": "https://skill.jobs",
    "listing_path": "/browse-jobs",
    "listing_pagination": "?page={page}",
    "max_pages": 10,
    "max_jobs_per_run": 60,
    "selectors": {
        "job_card": "article",
        "job_link": "a[href*='/jobs/']",
        "job_title": "h2, h3",
        "company": ".company, [class*='company']",
        "location": ".location, [class*='location']",
        "description": ".job-description, .description, [class*='description']",
        "posted_date": "[class*='date'], [class*='posted'], time",
        "salary": "[class*='salary'], [class*='pay']",
        "skills": "[class*='skill'], [class*='tag']"
    },
    "detail_url_pattern": "",
    "id_from_url": true,
    "robots_txt": "/robots.txt"
}
"""

from job_market_intel.scrapers.html_scraper.pipeline import HtmlScraperPipeline
from job_market_intel.scrapers.html_scraper.config import HtmlScraperSettings, SiteConfig, load_site_config, list_available_sites

__all__ = [
    "HtmlScraperPipeline",
    "HtmlScraperSettings",
    "SiteConfig",
    "load_site_config",
    "list_available_sites",
]
