"""Unit tests for the XpressJobs (xpress.jobs) scraper.

Pinned measured facts (2026-11-28, live site):

  * Discovery is ``GET https://xpress.jobs/api/jobs/searchJobs`` returning
    a **bare JSON array** pageable by ``page`` (1-based) with
    ``pageSize`` capped at 100 and ``sortBy=SortedCreateDate DESC``
    (deterministic, newest-first).
  * Every listing row is hydrated by ``GET
    https://xpress.jobs/api/jobs/publishedJob?jobId=<id>``; the public
    page is ``https://xpress.jobs/jobs/view/<id>``.
  * The listing's ``createdDate`` is always ``null``; only the detail
    carries the ISO ``createdDate`` (no timezone).
  * ``minSalary``/``maxSalary`` are strings: ``"Any"`` (and a placeholder
    ``"1"``) mean the figure is hidden.
  * ``jobType`` is observed as "Full-Time", "Permanent" and
    "Contract Basis".
  * robots.txt is a single ``User-agent: *`` group with an empty
    ``Disallow:`` (everything allowed).

No test touches the network.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from job_market_intel.cleaning.xpress_jobs_cleaner import (
    XpressJobsCleaner,
    map_employment_type,
)
from job_market_intel.scrapers.xpress_jobs.config import XpressJobsSettings
from job_market_intel.scrapers.xpress_jobs.models import RawXpressJob
from job_market_intel.scrapers.xpress_jobs.parser import XpressJobsParser
from job_market_intel.validation.xpress_jobs_validator import (
    XpressJobsBatchValidator,
    XpressJobsValidationSettings,
)

LISTING = {
    "jobId": 357454,
    "recruiterId": 17248,
    "jobTitle": "Material Engineer | Ruwanpura Express Way Project",
    "internalRef": None,
    "organizationId": 16721,
    "organizationName": "Senura Civil Engineering (Pvt) Ltd",
    "overview": "We are pleased to announce the commencement of a new project.",
    "createdDate": None,
    "expiryDateOnWebsite": "2026-12-10T00:00:00",
    "expireDayCountDown": 12,
    "jobType": "Full-Time",
    "locations": " Ratnapura, Sabaragamuwa Province",
    "priority": 0,
    "hasLogo": True,
    "logoImageUrl": "https://cdn.xpress.jobs/Organizations/logo_16721.jpg",
    "remote": False,
    "recordCount": 4143,
}

DETAIL = {
    "jobId": 357454,
    "jobTitle": "Material Engineer | Ruwanpura Express Way Project",
    "education": "Bachelor\u2019s Degree",
    "experience": "Similar Industry Experience ",
    "minSalary": "Any",
    "maxSalary": "Any",
    "salaryRange": "Any",
    "jobHasImage": False,
    "hasFiltering": True,
    "jobInfo": (
        "<p>Senura Civil Engineering (Pvt) Ltd is hiring.</p>"
        "<ul><li>B.Sc. in Civil Engineering</li></ul>"
    ),
    "jobImageUri": None,
    "benefits": None,
    "isRedirected": False,
    "redirectingUrl": None,
    "jobItem": dict(LISTING),
    "sectors": [
        {
            "sectorId": 18,
            "sectorCount": 238,
            "sectorName": "Building & Construction",
            "friendlyName": "construction",
        }
    ],
    "organization": {
        "organizationId": 16721,
        "organizationName": "Senura Civil Engineering (Pvt) Ltd",
        "city": "Kollupitiya",
        "hasLogo": True,
        "logoImageUrl": "https://cdn.xpress.jobs/Organizations/logo_16721.jpg",
        "liveJobCount": 36,
    },
    "metaKeywords": "Civil Engineer,Construction Jobs",
    "createdDate": "2026-11-26T05:43:41.707",
}


def _raw(listing: dict | None = None, detail: dict | None = DETAIL) -> dict:
    listing = LISTING if listing is None else listing
    job_id = listing.get("jobId", "")
    return {
        "url": f"https://xpress.jobs/jobs/view/{job_id}",
        "listing": listing,
        "detail": detail,
    }


class TestModels:
    def test_from_payload_merges_listing_and_detail(self) -> None:
        job = RawXpressJob.from_payload(
            LISTING, DETAIL, original_url="https://xpress.jobs/jobs/view/357454"
        )
        assert job.source_job_id == "357454"
        assert job.job_title == "Material Engineer | Ruwanpura Express Way Project"
        assert job.company_name == "Senura Civil Engineering (Pvt) Ltd"
        assert job.company_logo_url == "https://cdn.xpress.jobs/Organizations/logo_16721.jpg"
        assert job.location_text == "Ratnapura, Sabaragamuwa Province"
        assert job.employment_type_raw == "Full-Time"
        assert job.salary_min_raw is None  # "Any"
        assert job.salary_max_raw is None
        assert job.description_html is not None and job.description_html.startswith("<p>")
        assert job.posting_date is not None
        assert (job.posting_date.year, job.posting_date.month, job.posting_date.day) == (
            2026,
            11,
            26,
        )
        assert job.closing_date is not None
        assert (job.closing_date.year, job.closing_date.month, job.closing_date.day) == (
            2026,
            12,
            10,
        )
        assert job.raw_payload["sectors"] == ["Building & Construction"]
        assert job.original_url == "https://xpress.jobs/jobs/view/357454"

    def test_from_payload_listing_only_falls_back(self) -> None:
        job = RawXpressJob.from_payload(
            LISTING, None, original_url="https://xpress.jobs/jobs/view/357454"
        )
        assert job.source_job_id == "357454"
        assert job.job_title == LISTING["jobTitle"]
        assert job.company_name == LISTING["organizationName"]
        assert job.location_text == "Ratnapura, Sabaragamuwa Province"  # listing fallback
        assert job.employment_type_raw == "Full-Time"
        assert job.posting_date is None  # detail-only field
        assert job.closing_date is not None  # listing carries expiry
        assert job.description_html is None

    def test_real_salary_passes_through(self) -> None:
        detail = {**DETAIL, "minSalary": "40000", "maxSalary": "80000"}
        job = RawXpressJob.from_payload(LISTING, detail, original_url="https://x/")
        assert job.salary_min_raw == 40000
        assert job.salary_max_raw == 80000

    def test_placeholder_one_salary_is_none(self) -> None:
        detail = {**DETAIL, "minSalary": "1", "maxSalary": "1"}
        job = RawXpressJob.from_payload(LISTING, detail, original_url="https://x/")
        assert job.salary_min_raw is None
        assert job.salary_max_raw is None

    def test_single_bound_salary(self) -> None:
        detail = {**DETAIL, "minSalary": "60000", "maxSalary": "Any"}
        job = RawXpressJob.from_payload(LISTING, detail, original_url="https://x/")
        assert job.salary_min_raw == 60000
        assert job.salary_max_raw is None

    def test_from_payload_rejects_non_object_listing(self) -> None:
        with pytest.raises(ValueError):
            RawXpressJob.from_payload([], DETAIL, original_url="https://x/")

    def test_missing_title_is_rejected(self) -> None:
        listing = {**LISTING, "jobTitle": ""}
        detail = {**DETAIL, "jobTitle": ""}
        with pytest.raises(ValidationError):
            RawXpressJob.from_payload(listing, detail, original_url="https://x/")

    def test_missing_job_id_is_rejected(self) -> None:
        listing = {**LISTING, "jobId": ""}
        detail = {**DETAIL, "jobId": ""}
        with pytest.raises(ValidationError):
            RawXpressJob.from_payload(listing, detail, original_url="https://x/")


class TestParser:
    def test_parses_valid_and_skips_malformed(self) -> None:
        parser = XpressJobsParser()
        raw = [
            _raw(),
            {"url": "", "listing": None, "detail": None},  # malformed: no listing
            {"url": "https://x/", "listing": {**LISTING, "jobId": ""}, "detail": None},
        ]
        jobs = parser.parse_jobs(raw)
        assert len(jobs) == 1
        assert jobs[0].source_job_id == "357454"


class TestCleaner:
    def test_salary_and_currency(self) -> None:
        detail = {**DETAIL, "minSalary": "40000", "maxSalary": "80000"}
        job = RawXpressJob.from_payload(LISTING, detail, original_url="https://x/")
        cleaned = XpressJobsCleaner().clean_job(job)
        assert cleaned.salary_min == 40000
        assert cleaned.salary_max == 80000
        assert cleaned.salary_disclosed is True
        assert cleaned.currency_iso_code == "LKR"
        assert cleaned.pay_period == "monthly"
        assert cleaned.employment_type_code == "full_time"
        assert cleaned.remote_work_type_code is None
        assert cleaned.skills == []
        assert "B.Sc. in Civil Engineering" in (cleaned.description_clean or "")

    def test_any_salary_is_undisclosed(self) -> None:
        job = RawXpressJob.from_payload(LISTING, DETAIL, original_url="https://x/")
        cleaned = XpressJobsCleaner().clean_job(job)
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_reversed_salary_is_swapped(self) -> None:
        detail = {**DETAIL, "minSalary": "90000", "maxSalary": "30000"}
        job = RawXpressJob.from_payload(LISTING, detail, original_url="https://x/")
        cleaned = XpressJobsCleaner().clean_job(job)
        assert cleaned.salary_min == 30000
        assert cleaned.salary_max == 90000

    def test_permanent_maps_to_full_time(self) -> None:
        assert map_employment_type("Permanent") == "full_time"
        assert map_employment_type("Contract Basis") == "contract"
        assert map_employment_type("Part-Time") == "part_time"
        assert map_employment_type("Volunteer-ish") is None

    def test_closing_before_posting_is_dropped(self) -> None:
        detail = {**DETAIL, "createdDate": "2026-11-26T05:43:41.707"}
        listing = {**LISTING, "expiryDateOnWebsite": "2026-11-20T00:00:00"}
        job = RawXpressJob.from_payload(listing, detail, original_url="https://x/")
        cleaned = XpressJobsCleaner().clean_job(job)
        assert cleaned.closing_date is None

    def test_clean_jobs_batch(self) -> None:
        job = RawXpressJob.from_payload(LISTING, DETAIL, original_url="https://x/")
        cleaned = XpressJobsCleaner().clean_jobs([job, job])
        assert len(cleaned) == 2

    def test_posted_date_is_datetime(self) -> None:
        job = RawXpressJob.from_payload(LISTING, DETAIL, original_url="https://x/")
        cleaned = XpressJobsCleaner().clean_job(job)
        assert isinstance(cleaned.posting_date, datetime)


class TestValidator:
    def _jobs(self, n: int) -> list[RawXpressJob]:
        return [
            RawXpressJob.from_payload(
                {**LISTING, "jobId": 100000 + i},
                DETAIL,
                original_url=f"https://xpress.jobs/jobs/view/{100000 + i}",
            )
            for i in range(n)
        ]

    def test_healthy_batch_passes(self) -> None:
        jobs = self._jobs(60)
        report = XpressJobsBatchValidator().validate(list(jobs), jobs)
        assert report.passed is True
        assert report.total_parsed == 60

    def test_too_few_jobs_fails(self) -> None:
        jobs = self._jobs(3)
        report = XpressJobsBatchValidator().validate(list(jobs), jobs)
        assert report.passed is False
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_zero_raw_records_fails(self) -> None:
        report = XpressJobsBatchValidator().validate([], [])
        assert report.passed is False

    def test_duplicate_ids_are_flagged(self) -> None:
        jobs = self._jobs(60)
        report = XpressJobsBatchValidator().validate(list(jobs), jobs + [jobs[0]])
        assert report.passed is False
        assert report.duplicate_source_job_ids == ["100000"]

    def test_default_thresholds(self) -> None:
        settings = XpressJobsValidationSettings()
        assert settings.min_expected_jobs == 50
        assert settings.max_skip_rate == 0.10


class TestSettings:
    def test_defaults(self) -> None:
        settings = XpressJobsSettings()
        assert settings.page_size == 100
        assert settings.max_jobs_per_run == 200
        assert settings.sort_by == "SortedCreateDate DESC"
        assert settings.search_url.endswith("/api/jobs/searchJobs")
        assert settings.detail_url.endswith("/api/jobs/publishedJob")
        assert settings.user_agent.startswith("Mozilla/5.0")
