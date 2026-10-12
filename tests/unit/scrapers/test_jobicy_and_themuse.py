"""tests/unit/scrapers/test_jobicy_and_themuse.py

Jobicy and The Muse were both added on 2026-10-12. The tests here cover the
contracts that live API probing established, because each was a bug the first
time the pipeline actually ran:

* ``test_pay_period_must_not_be_none`` -- ``CleanedJob.pay_period`` is a
  required ``str``. Passing None raised ``Input should be a valid string
  [type=string_type]`` and silently dropped every row of the batch, while the
  run summary still said "29 cleaned" only because the log showed 29 errors.

* ``test_original_url_is_never_empty`` -- ``core.jobs.original_url`` is NOT
  NULL, and The Muse carries no canonical job URL, only a company landing
  page.

* ``test_stale_drop`` -- The Muse is not time-ordered; publication dates on
  the first three pages spanned 2025-01-17 to 2026-10-03, so the age filter is
  the only thing keeping historical vacancies out.

Payloads below were captured from the live APIs on 2026-10-12 and trimmed.
"""

from __future__ import annotations

import datetime as dt

import pytest

from job_market_intel.cleaning.jobicy_cleaner import (
    DEFAULT_PAY_PERIOD as JOBICY_PAY_PERIOD,
)
from job_market_intel.cleaning.jobicy_cleaner import JobicyCleaner
from job_market_intel.cleaning.themuse_cleaner import ThemuseCleaner
from job_market_intel.scrapers.jobicy.parser import JobicyParser
from job_market_intel.scrapers.themuse.parser import ThemuseParser


def _jobicy_record(**overrides) -> dict:
    base = {
        "id": 155052,
        "jobTitle": "Senior Backend Engineer",
        "companyName": "Acme",
        "companyLogo": "https://jobicy.com/logo.png",
        "jobGeo": "USA",
        "jobIndustry": ["Software Development"],
        "jobType": ["Full-Time"],
        "jobLevel": "Senior",
        "jobDescription": "<p>Build things.</p>",
        "jobExcerpt": "Build things.",
        "pubDate": "2026-10-11T08:39:51+00:00",
        "url": "https://jobicy.com/jobs/155052",
    }
    base.update(overrides)
    return base


def _themuse_record(**overrides) -> dict:
    base = {
        "id": 19225596,
        "name": "Registered Nurse Med/Surg Telemetry",
        "company": {"id": 15000905, "short_name": "example", "name": "Example Health"},
        "contents": "<p><b>Up to $25,000 sign on bonus.</b></p>",
        "publication_date": "2026-10-03T09:59:33Z",
        "categories": [{"name": "Healthcare"}],
        "levels": [{"name": "Mid Level", "short_name": "mid"}],
        "locations": [{"name": "Dearborn, MI"}],
        "tags": [],
        "refs": {"landing_page": "https://www.themuse.com/companies/example"},
    }
    base.update(overrides)
    return base


class TestJobicyModels:
    def test_numeric_id_is_stringified_at_the_boundary(self):
        job = JobicyParser().parse_jobs([_jobicy_record()])[0]
        assert job.id == "155052"
        assert job.source_job_id == "155052"

    def test_pay_period_must_not_be_none(self):
        """CleanedJob.pay_period is a required str; None drops the row."""
        cleaned = JobicyCleaner().clean_jobs(JobicyParser().parse_jobs([_jobicy_record()]))[0]
        assert cleaned.pay_period == JOBICY_PAY_PERIOD
        assert isinstance(cleaned.pay_period, str) and cleaned.pay_period

    def test_missing_optional_lists_are_tolerated(self):
        job = JobicyParser().parse_jobs(
            [_jobicy_record(jobIndustry=[], jobType=[], jobGeo=None, jobLevel=None)]
        )[0]
        assert job.jobIndustry == []
        cleaned = JobicyCleaner().clean_job(job)
        assert cleaned.location_cleaned  # falls back to the remote placeholder

    def test_naive_pubdate_is_assumed_utc_not_stored_naive(self):
        job = JobicyParser().parse_jobs([_jobicy_record(pubDate="2026-10-11T08:39:51")])[0]
        assert job.posting_date.tzinfo is not None

    def test_industry_filter_drops_non_technical(self):
        jobs = JobicyParser().parse_jobs(
            [_jobicy_record(jobIndustry=["Healthcare"])]
        )
        assert JobicyParser.filter_focus(jobs, ["software"]) == []

    def test_industry_filter_matches_compound_labels(self):
        jobs = JobicyParser().parse_jobs(
            [_jobicy_record(jobIndustry=["Data Science & Analytics"])]
        )
        assert len(JobicyParser.filter_focus(jobs, ["data science"])) == 1


class TestThemuseModels:
    def test_nested_company_is_flattened(self):
        job = ThemuseParser().parse_jobs([_themuse_record()])[0]
        assert job.company_name == "Example Health"

    def test_nested_locations_become_one_string(self):
        job = ThemuseParser().parse_jobs(
            [_themuse_record(locations=[{"name": "Dearborn, MI"}, {"name": "Detroit, MI"}])]
        )[0]
        assert job.location_text == "Dearborn, MI, Detroit, MI"

    def test_original_url_is_never_empty(self):
        """original_url is NOT NULL and The Muse has no canonical job URL."""
        job = ThemuseParser().parse_jobs([_themuse_record(refs={})])[0]
        cleaned = ThemuseCleaner().clean_job(job)
        assert cleaned.original_url
        assert "19225596" in cleaned.original_url

    def test_landing_page_is_preferred_when_present(self):
        job = ThemuseParser().parse_jobs([_themuse_record()])[0]
        cleaned = ThemuseCleaner().clean_job(job)
        assert cleaned.original_url == "https://www.themuse.com/companies/example"

    def test_stale_postings_are_dropped(self):
        """The feed is not time-ordered, so this filter is load-bearing."""
        old = _themuse_record(publication_date="2025-01-17T12:00:00Z")
        jobs = ThemuseParser().parse_jobs([old, _themuse_record()])
        kept = ThemuseParser.drop_stale(jobs, max_age_days=45)
        assert len(kept) == 1
        assert kept[0].id == "19225596"

    def test_undated_postings_are_kept_not_discarded(self):
        """An unknown date is not evidence of staleness."""
        jobs = ThemuseParser().parse_jobs(
            [_themuse_record(publication_date=None), _themuse_record(publication_date="bad")]
        )
        assert len(ThemuseParser.drop_stale(jobs, max_age_days=45)) == 2

    def test_freshness_cutoff_is_honoured_at_the_boundary(self):
        exactly_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=45)
        job = ThemuseParser().parse_jobs(
            [_themuse_record(publication_date=exactly_at.isoformat())]
        )[0]
        kept = ThemuseParser.drop_stale([job], max_age_days=44)
        assert kept == []

    def test_source_job_id_alias_exists(self):
        job = ThemuseParser().parse_jobs([_themuse_record()])[0]
        assert job.source_job_id == "19225596"


class TestSkipBadRecords:
    """One malformed record must never end a run."""

    @pytest.mark.parametrize(
        ("parser_cls", "record_factory"),
        [(JobicyParser, _jobicy_record), (ThemuseParser, _themuse_record)],
    )
    def test_malformed_records_are_skipped_not_fatal(self, parser_cls, record_factory):
        bad = record_factory(id=None)
        parsed = parser_cls().parse_jobs([bad, "not a dict", 42])
        assert parsed == []

    def test_a_good_record_survives_alongside_bad_ones(self):
        parsed = JobicyParser().parse_jobs([_jobicy_record(), {"jobTitle": "no id"}])
        assert len(parsed) == 1

    def test_themuse_good_record_survives_alongside_bad_ones(self):
        parsed = ThemuseParser().parse_jobs([_themuse_record(), {"name": "no id"}])
        assert len(parsed) == 1
