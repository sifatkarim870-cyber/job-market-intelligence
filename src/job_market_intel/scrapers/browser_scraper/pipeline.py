"""Pipeline for the generic browser (Selenium) scraper framework.

This is the HTML framework's pipeline with one substitution: the client. The
parser, the quality gate, the batch validator, the cleaner and the persistence
path are the same objects, so a posting that the HTML framework would reject is
rejected here for the same reason.
"""

from __future__ import annotations

from typing import Any

from job_market_intel.scrapers.html_scraper.pipeline import (
    HtmlScraperPipeline,
    HtmlScraperPipelineRunResult,
)

from .client import BrowserScraperClient
from .config import BrowserScraperSettings, BrowserSiteConfig, load_browser_site_config


class BrowserScraperPipeline(HtmlScraperPipeline):
    """Renders a site in Chrome and stores the postings it finds."""

    def __init__(
        self,
        source_code: str,
        settings: BrowserScraperSettings | None = None,
        validation_settings: Any | None = None,
        client: BrowserScraperClient | None = None,
        parser: Any | None = None,
        validator: Any | None = None,
        cleaner: Any | None = None,
        site_config: BrowserSiteConfig | None = None,
    ) -> None:
        self._browser_settings = settings or BrowserScraperSettings()
        self._browser_site_config = site_config or load_browser_site_config(
            source_code, self._browser_settings.sites_dir
        )
        super().__init__(
            source_code=source_code,
            settings=self._browser_settings,  # type: ignore[arg-type]
            validation_settings=validation_settings,
            client=client
            or BrowserScraperClient(source_code, self._browser_settings, self._browser_site_config),
            parser=parser,
            validator=validator,
            cleaner=cleaner,
            site_config=self._browser_site_config,
        )

    def run(
        self, *, store_db: bool = True, max_jobs: int | None = None
    ) -> HtmlScraperPipelineRunResult:
        return super().run(store_db=store_db, max_jobs=max_jobs)
