"""Configuration for the generic HTML scraper framework.

Each site is configured via a JSON file in sites/ directory.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: The link selector the config generator writes for every site it cannot
#: inspect. It is a hypothesis, not a verified selector, so discovery applies
#: the same URL test to its matches that auto-detection uses.
GENERIC_LINK_SELECTOR = (
    "a[href*='/job/'], a[href*='/vacancy/'], a[href*='/listing/'], a[href*='/career/']"
)


class SelectorConfig(BaseModel):
    job_card: str = Field(default="", description="CSS selector for job listing cards")
    job_link: str = Field(default="", description="CSS selector for job detail link")
    job_title: str = Field(default="", description="CSS selector for job title")
    company: str = Field(default="", description="CSS selector for company name")
    location: str = Field(default="", description="CSS selector for location")
    description: str = Field(default="", description="CSS selector for job description")
    posted_date: str = Field(default="", description="CSS selector for posting date")
    salary: str = Field(default="", description="CSS selector for salary")
    skills: str = Field(default="", description="CSS selector for skills list")
    employment_type: str = Field(default="", description="CSS selector for employment type")


class SiteConfig(BaseModel):
    source_code: str = Field(..., description="Unique source code")
    source_name: str = Field(..., description="Human-readable source name")
    country: str = Field(..., description="Country name")
    base_url: str = Field(..., description="Site base URL")
    listing_path: str = Field(default="/jobs", description="Listing page path")
    listing_pagination: str = Field(default="?page={page}", description="Pagination URL pattern")
    max_pages: int = Field(default=10, ge=1, description="Max listing pages")
    max_jobs_per_run: int = Field(default=60, ge=1, description="Max jobs per run")
    min_expected_jobs: int = Field(
        default=1, ge=1, description="Minimum expected jobs per run for validation"
    )
    selectors: SelectorConfig = Field(default_factory=SelectorConfig)
    #: Which title source to trust, most-trusted first. "h1" is the job's name
    #: on a rendered posting page; "og:title" is the SEO string, which on
    #: some boards is the *posting's* title and on others is a category
    #: heading with the site name appended. A site that knows which is which
    #: says so here.
    title_priority: str = Field(
        default="h1,og:title,title-tag,selector",
        description="Comma-separated title sources, most trusted first.",
    )
    detail_url_pattern: str = Field(default="", description="Detail URL pattern")
    id_from_url: bool = Field(default=True, description="Extract job ID from URL")
    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA",
    )
    request_timeout_seconds: int = Field(default=30, ge=1)
    inter_request_delay_seconds: float = Field(default=0.1, ge=0.0)
    currency_iso_code: str = Field(default="USD", description="Default currency")
    pay_period: str = Field(default="monthly", description="Default pay period")
    country_fallback: str = Field(default="", description="Fallback country name")


class HtmlScraperSettings(BaseSettings):
    """Global settings for the HTML scraper framework."""

    model_config = SettingsConfigDict(env_prefix="HTML_SCRAPER_", extra="ignore")

    @property
    def sites_dir(self) -> str:
        """Absolute path to the sites config directory."""
        # __file__ is scrapers/html_scraper/config.py; parents[4] is the project root.
        project_root = Path(__file__).resolve().parents[4]
        return str(
            project_root / "src" / "job_market_intel" / "scrapers" / "html_scraper" / "sites"
        )


def load_site_config(source_code: str, sites_dir: str | None = None) -> SiteConfig:
    """Load a site config from JSON file.

    ``sites_dir`` used to default to the relative string
    ``scrapers/html_scraper/sites``, which only exists if the process happens to
    run from inside ``src/``. Every caller passed the absolute settings path, so
    the broken default was never exercised -- calling it without an argument
    raised ``FileNotFoundError``. It now resolves through the settings object.
    """
    config_path = Path(sites_dir or HtmlScraperSettings().sites_dir) / f"{source_code}.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Site config not found: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)
    return SiteConfig(**data)


def list_available_sites(sites_dir: str | None = None) -> list[str]:
    """List all available site config files."""
    sites_path = Path(sites_dir or HtmlScraperSettings().sites_dir)
    if not sites_path.exists():
        return []
    return sorted(p.stem for p in sites_path.glob("*.json"))
