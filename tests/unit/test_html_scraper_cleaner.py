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


def test_cleaner_extracts_features_from_multilingual_and_translated_text() -> None:
    raw = RawHtmlScraperJob(
        source_job_id="test-fa-1",
        title="توسعه دهنده ارشد بک اند",
        company_name="دیجیکالا",
        description="ما به دنبال یک توسعه دهنده با حداقل ۳ سال سابقه کار هستیم. مزایا: بیمه تامین اجتماعی و ناهار.",
        location="Tehran",
        country="Iran",
        posted_date=date(2026, 11, 1),
        url="https://example.invalid/jobs/fa-1",
        raw={
            "job_title_en": "Senior Backend Developer",
            "description_en": "We are looking for a Senior Backend Developer with at least 3 years of experience in Python and PostgreSQL. Benefits include health insurance and lunch.",
        },
    )

    cleaner = HtmlScraperCleaner()
    job = cleaner.clean_job(raw)

    assert job.experience_years_min == 3
    assert job.seniority_role_type == "individual_contributor"
    assert job.is_managerial is False
    assert job.job_category_code == "swe_backend"
    assert "health_insurance" in (job.benefits_normalized or "")
    assert "python" in (job.skills_normalized or "")
    assert "postgresql" in (job.skills_normalized or "")
