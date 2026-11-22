"""Pipeline for the OCC Mundial (Mexico) scraper.

This is the HTML framework's pipeline with one substitution: the client. The
parser, the quality gate, the batch validator, the cleaner and the persistence
path are the same objects, so a posting that the HTML framework would reject is
rejected here for the same reason.
"""

from __future__ import annotations

from typing import Any

from job_market_intel.scrapers.browser_scraper.config import (
    BrowserScraperSettings,
    BrowserSiteConfig,
    load_browser_site_config,
)
from job_market_intel.scrapers.html_scraper.pipeline import (
    HtmlScraperPipeline,
    HtmlScraperPipelineRunResult,
)

from .client import OccComMxClient

SOURCE_CODE = "occ_com_mx"


class OccComMxPipeline(HtmlScraperPipeline):
    """Runs the OCC Mundial client through the shared HTML pipeline."""

    def __init__(
        self,
        source_code: str = SOURCE_CODE,
        settings: BrowserScraperSettings | None = None,
        validation_settings: Any | None = None,
        client: OccComMxClient | None = None,
        parser: Any | None = None,
        validator: Any | None = None,
        cleaner: Any | None = None,
        site_config: BrowserSiteConfig | None = None,
    ) -> None:
        browser_settings = settings or BrowserScraperSettings()
        browser_site_config = site_config or load_browser_site_config(
            source_code, browser_settings.sites_dir
        )
        super().__init__(
            source_code=source_code,
            settings=browser_settings,  # type: ignore[arg-type]
            validation_settings=validation_settings,
            client=client
            or OccComMxClient(source_code, browser_settings, browser_site_config),
            parser=parser,
            validator=validator,
            cleaner=cleaner,
            site_config=browser_site_config,
        )

    def run(
        self, *, store_db: bool = True, max_jobs: int | None = None
    ) -> HtmlScraperPipelineRunResult:
        return super().run(store_db=store_db, max_jobs=max_jobs)
