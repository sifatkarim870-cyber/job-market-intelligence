"""Unit tests for the Fiji Sun jobs scraper.

Pinned measured facts (2026-10-18):
  * NO JSON-LD; og:title/og:description are SITE-wide and must not be used.
  * title from <h1>; company from <h1>'s parent minus the <h1>.
  * posting date is RELATIVE ('Posted 1 week ago') -> derived.
  * closing date is ABSOLUTE ('Closes 5 November 2026').
  * Salary reads 'T.B.D.' -- not a figure.
  * /jobs/browse is the real pager (2 new); /jobs/page/2 and ?page=2 give 0.
"""

from __future__ import annotations

from datetime import date

import pytest

from job_market_intel.cleaning.fijisun_jobs_cleaner import FijiSunJobsCleaner
from job_market_intel.scrapers.fijisun_jobs.client import FijiSunJobsClient, _is_posting_slug
from job_market_intel.scrapers.fijisun_jobs.config import FijiSunJobsSettings
from job_market_intel.scrapers.fijisun_jobs.exceptions import (
    FijiSunJobsResponseError,
)
from job_market_intel.scrapers.fijisun_jobs.models import _parse_relative_posted
from job_market_intel.scrapers.fijisun_jobs.parser import (
    FijiSunJobsParser,
    parse_detail,
)

DETAIL = """<!DOCTYPE html><html><head>
<title>Advertising Sales Executive (West) at Fiji Sun  | Fiji Sun Jobs</title>
<meta property="og:title" content="Fiji Sun - Your Trusted Source for Fiji News">
<meta property="og:description" content="Catch up on the latest headlines.">
</head><body>
<div class="flex items-start gap-4">
  <h1>Advertising Sales Executive (West)</h1>
  Fiji Sun
</div>
<aside class="h-fit space-y-4 lg:sticky lg:top-6">
  <div class="border border-neutral-300">
    <div>Job overview</div>
    <div>Posted</div><div>1 week ago</div>
    <div>Salary</div><div>T.B.D.</div>
    <div>Openings</div><div>1 position</div>
    <div>Experience</div><div>1+ yrs exp.</div>
    <div>Type</div><div>Full-time</div>
    <div>Location</div><div>Lautoka</div>
    <div>Closes</div><div>5 November 2026</div>
  </div>
</aside>
<div class="mt-6 whitespace-pre-line font-serif text-neutral-700">
  Fiji Sun is looking for a motivated and results-driven professional to sell
  print and digital advertising solutions and build lasting client relationships
  across the western division.
</div>
</body></html>"""

OG_TRAP = """<!DOCTYPE html><html><head>
<title>Chief Financial Officer- Fiji Airways at KPMG  | Fiji Sun Jobs</title>
<meta property="og:title" content="Fiji Sun - Your Trusted Source for Fiji News">
</head><body>
<div class="flex items-start gap-4">
  <h1>Chief Financial Officer- Fiji Airways</h1>
  KPMG
</div>
<aside class="h-fit space-y-4 lg:sticky lg:top-6">
  <div class="border border-neutral-300">
    <div>Job overview</div>
    <div>Posted</div><div>3 days ago</div>
    <div>Type</div><div>Full-time</div>
    <div>Location</div><div>Nadi</div>
    <div>Closes</div><div>25 October 2026</div>
  </div>
</aside>
<div class="mt-6 whitespace-pre-line font-serif text-neutral-700">
  About the role and responsibilities for the chief financial officer position
  supporting the finance and operations of the organisation in Fiji.
</div>
</body></html>"""


class TestListingLinks:
    def test_pagination_is_path_based(self):
        client = FijiSunJobsClient(FijiSunJobsSettings())
        assert client.listing_url(1) == "https://fijisun.com.fj/jobs"
        assert client.listing_url(2) == "https://fijisun.com.fj/jobs/browse"

    def test_empty_discovery_raises(self):
        client = FijiSunJobsClient(FijiSunJobsSettings())
        client._fetch = lambda url: "<html><body>nothing</body></html>"
        with pytest.raises(FijiSunJobsResponseError, match="markup changed"):
            client.discover_detail_paths()

    def test_chrome_slugs_excluded(self):
        assert _is_posting_slug("advertising-sales-executive-west-930m7") is True
        for bad in ("browse", "page", "search", ""):
            assert _is_posting_slug(bad) is False


class TestOgTitleTrap:
    """THE trap: og:title is site-wide. Trusting it stores the wrong title."""

    def test_title_comes_from_h1_not_og(self):
        job = parse_detail("advertising-sales-executive-west-930m7", DETAIL)
        assert job.title == "Advertising Sales Executive (West)"
        assert "Fiji Sun - Your Trusted Source" not in job.title

    def test_company_is_extracted_from_the_card_header(self):
        job = parse_detail("advertising-sales-executive-west-930m7", DETAIL)
        assert job.company_name == "Fiji Sun"

    def test_og_title_is_recorded_for_audit_not_used(self):
        job = parse_detail("advertising-sales-executive-west-930m7", DETAIL)
        assert job.raw["og_title"] == "Fiji Sun - Your Trusted Source for Fiji News"

    def test_a_title_containing_a_dash_keeps_its_company(self):
        job = parse_detail("chief-financial-officer-phrmc", OG_TRAP)
        assert job.title == "Chief Financial Officer- Fiji Airways"
        assert job.company_name == "KPMG"


class TestDates:
    def test_posted_is_derived_from_a_relative_phrase(self):
        from datetime import date, timedelta

        job = parse_detail("advertising-sales-executive-west-930m7", DETAIL)
        assert job.posted_date == date.today() - timedelta(weeks=1)
        assert job.posted_phrase == "1 week ago"
        assert job.raw["derived_posted_date"] is not None

    def test_closing_is_read_from_closes(self):
        job = parse_detail("advertising-sales-executive-west-930m7", DETAIL)
        assert job.closing_date == date(2026, 11, 5)

    def test_a_page_with_no_posted_phrase_has_no_posted_date(self):
        html = DETAIL.replace("<div>1 week ago</div>", "<div>(not stated)</div>")
        job = parse_detail("x", html)
        assert job.posted_date is None


class TestRelativeParser:
    def test_days_weeks_months(self):
        assert _parse_relative_posted("Posted 3 days ago", date(2026, 10, 17)) == date(2026, 10, 14)
        assert _parse_relative_posted("Posted 1 week ago", date(2026, 10, 17)) == date(2026, 10, 10)
        assert _parse_relative_posted("Posted 2 months ago", date(2026, 10, 17)) == date(
            2026, 8, 18
        )
        assert _parse_relative_posted("no relative phrase here", date(2026, 10, 17)) is None


class TestCleaner:
    def _job(self, **kw):
        return parse_detail("advertising-sales-executive-west-930m7", DETAIL).model_copy(update=kw)

    def test_posted_date_is_derived_flag(self):
        cleaned = FijiSunJobsCleaner().clean_job(self._job())
        assert cleaned.raw_payload["posted_date_is_derived"] is True

    def test_no_salary_is_ever_claimed(self):
        cleaned = FijiSunJobsCleaner().clean_job(self._job())
        assert cleaned.salary_min is None
        assert cleaned.salary_disclosed is False

    def test_skills_are_empty(self):
        assert FijiSunJobsCleaner().clean_job(self._job()).skills == []

    def test_country_is_fj(self):
        payload = FijiSunJobsCleaner().clean_job(self._job()).raw_payload
        assert payload["country_iso"] == "FJ"


class TestValidator:
    def _report(self, n=8, html=DETAIL):
        from job_market_intel.validation.fijisun_jobs_validator import FijiSunJobsBatchValidator

        parser = FijiSunJobsParser()
        raw = [{"job_id": f"slug-{i}", "html": html} for i in range(n)]
        parsed = [parser.parse(r["job_id"], r["html"]) for r in raw]
        return FijiSunJobsBatchValidator().validate(raw, parsed)

    def test_a_full_batch_passes(self):
        assert self._report().passed

    def test_a_thin_batch_fails(self):
        assert not self._report(n=2).passed


class TestSettings:
    def test_defaults(self):
        s = FijiSunJobsSettings()
        assert s.base_url == "https://fijisun.com.fj"
        assert s.listing_path == "/jobs"

    def test_overrides(self):
        s = FijiSunJobsSettings(max_jobs_per_run=10)
        assert s.max_jobs_per_run == 10

    def test_rejects_nonsense(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            FijiSunJobsSettings(inter_request_delay_seconds=-1.0)
