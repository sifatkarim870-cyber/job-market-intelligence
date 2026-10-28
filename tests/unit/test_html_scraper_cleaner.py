"""The generic HTML cleaner takes currency and pay period from the board.

Every html source shared one cleaner that stamped "USD" and "monthly" on
every record, so a New Zealand hourly board such as MSD was stored with a
US-dollar monthly salary (2026-10-28).
"""

from __future__ import annotations

from datetime import date

from job_market_intel.cleaning.html_scraper_cleaner import HtmlScraperCleaner
from job_market_intel.scrapers.html_scraper.config import SiteConfig
from job_market_intel.scrapers.html_scraper.models import RawHtmlScraperJob
from job_market_intel.scrapers.html_scraper.pipeline import HtmlScraperPipeline


def _raw() -> RawHtmlScraperJob:
    return RawHtmlScraperJob(
        source_job_id="1",
        title="Cleaner/Janitor",
        company_name="Unknown employer",
        description="A food production factory is looking for a cleaner.",
        location="Marton",
        country="New Zealand",
        employment_type="Full-time",
        posted_date=date(2026, 10, 28),
        url="https://example.invalid/jobs/1",
    )


def test_cleaner_defaults_to_usd_monthly_for_direct_callers() -> None:
    job = HtmlScraperCleaner().clean_job(_raw())

    assert job.currency_iso_code == "USD"
    assert job.pay_period == "monthly"


def test_cleaner_uses_the_boards_currency_and_period() -> None:
    job = HtmlScraperCleaner(currency_iso_code="NZD", pay_period="hourly").clean_job(_raw())

    assert job.currency_iso_code == "NZD"
    assert job.pay_period == "hourly"


def test_pipeline_passes_the_site_config_to_the_cleaner() -> None:
    config = SiteConfig(
        source_code="unit_test",
        source_name="Unit test board",
        country="New Zealand",
        base_url="https://example.invalid",
        currency_iso_code="NZD",
        pay_period="hourly",
    )
    pipeline = HtmlScraperPipeline("unit_test", site_config=config)

    job = pipeline._cleaner.clean_job(_raw())

    assert job.currency_iso_code == "NZD"
    assert job.pay_period == "hourly"
