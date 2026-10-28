"""Configuration for the generic browser (Selenium) scraper framework.

Same idea as the HTML framework -- one JSON file per site -- but the pages are
rendered by a real Chrome before they are parsed. Sites that ship their job
listings as client-side JavaScript return an empty document to ``requests`` and
a full one to a browser.

The site config is a superset of the HTML framework's ``SiteConfig`` so the
parser, the quality gate, the validator, the cleaner and the persistence path
are the *same code*, not a copy that drifts.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from job_market_intel.scrapers.html_scraper.config import (
    HtmlScraperSettings,
    SiteConfig,
)


class BrowserSiteConfig(SiteConfig):
    """One browser-scraped site.

    Inherits every HTML-framework field (base_url, listing_path, selectors,
    detail_url_pattern, ...) and adds the knobs a real browser needs.
    """

    #: Wait for this selector to appear on a rendered listing page before
    #: reading it. Empty means "wait for document ready and take what is there".
    listing_ready_selector: str = Field(default="")
    #: Seconds to wait for the listing's own content. A JS board that has not
    #: finished rendering its cards yet yields an empty listing, not an error.
    listing_wait_seconds: int = Field(default=15, ge=1, le=180)
    #: Selector that marks a rendered detail page's body. Used to wait before
    #: reading a detail page.
    detail_ready_selector: str = Field(default="")
    detail_wait_seconds: int = Field(default=10, ge=1, le=180)
    #: Extra seconds to wait after the detail selector appears but before the
    #: page is read. A selector is only the *first* fragment to arrive on an
    #: Angular/React page: measured on Töötukassa (2026-10-28), the title was
    #: present while the employer block and the requirements section were still
    #: rendering, so half an ad was captured. Zero keeps the old behaviour.
    detail_settle_seconds: float = Field(default=0.0, ge=0.0, le=60.0)
    #: Scroll the listing to the bottom this many times before reading it.
    #: Many boards render the first screenful and load the rest on scroll.
    scroll_count: int = Field(default=0, ge=0, le=20)
    scroll_pause_seconds: float = Field(default=1.5, ge=0.0, le=30.0)
    #: Boards with a "load more" button render 20 ads and then wait for a click
    #: (Töötukassa's "Laadi veel"). When set, this selector is clicked
    #: :attr:`listing_more_clicks` times, waiting :attr:`listing_more_pause_seconds`
    #: after each click, before the page source is read.
    listing_more_selector: str = Field(
        default="", description="CSS selector for a 'load more' control on the listing"
    )
    listing_more_clicks: int = Field(default=0, ge=0, le=20)
    listing_more_pause_seconds: float = Field(default=3.0, ge=0.0, le=30.0)
    #: Undetected-Chrome mode (seleniumbase). On by default: a plainly
    #: fingerprinted WebDriver is refused by most of the boards this framework
    #: exists for.
    uc_mode: bool = Field(default=True)
    headless: bool = Field(default=True)
    #: Extra Chrome flags, space separated.
    chrome_args: str = Field(default="")
    #: Page text that means "we were served a challenge, not the site".
    challenge_markers: str = Field(default="")
    #: Cap on detail pages per run, independent of max_jobs.
    max_detail_pages: int = Field(default=40, ge=1, le=500)


class BrowserScraperSettings(HtmlScraperSettings):
    """Settings for the browser framework."""

    model_config = SettingsConfigDict(env_prefix="BROWSER_SCRAPER_", extra="ignore")

    @property
    def sites_dir(self) -> str:
        """Absolute path to the browser site config directory."""
        project_root = Path(__file__).resolve().parents[4]
        return str(
            project_root / "src" / "job_market_intel" / "scrapers" / "browser_scraper" / "sites"
        )


def load_browser_site_config(source_code: str, sites_dir: str | None = None) -> BrowserSiteConfig:
    """Load a browser site config from JSON."""
    config_path = Path(sites_dir or BrowserScraperSettings().sites_dir) / f"{source_code}.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Browser site config not found: {config_path}")
    with open(config_path, encoding="utf-8") as handle:
        data = json.load(handle)
    return BrowserSiteConfig(**data)


def list_available_browser_sites(sites_dir: str | None = None) -> list[str]:
    """List all available browser site config files."""
    sites_path = Path(sites_dir or BrowserScraperSettings().sites_dir)
    if not sites_path.exists():
        return []
    return sorted(path.stem for path in sites_path.glob("*.json"))
