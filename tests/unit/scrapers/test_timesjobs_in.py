"""Unit tests for the TimesJobs (timesjobs.com) scraper.

Pinned measured facts (2026-11-21, live site):

  * Discovery is ``POST
    https://tjapi.timesjobs.com/search/api/v1/search/jobs/list`` returning
    ``{total, page, size, totalPages, jobs}``; the default feed is
    newest-first by ``postDate`` and ``size`` accepts at least 500.
  * Every listing row is hydrated by ``GET
    https://tjapi.timesjobs.com/job-api/api/jobs/public/<token>`` where
    ``token`` is the text after ``jobid-`` in ``jobDetailUrl`` (including
    its trailing ``&source=srp``), sent as one URL-encoded path segment.
  * ``jobId`` is the stable ``source_job_id`` (a string in the listing, an
    int in the detail).
  * The listing ``description`` is truncated (~220-250 chars) while the
    detail carries full HTML; ``skills`` is a whitespace-run-separated
    string.
  * Salary is effectively hidden: every sampled detail row carried
    ``hideCtcFromCandidate: true`` with ``minCtc``/``maxCtc`` at ``-1``;
    ``ctcCurrency`` is the raw enum ``"r"`` and the listing ``currency`` is
    always ``"INR"``.
  * ``employmentType`` is usually ``"Full-time"`` but occasionally repeats
    the work mode ``"On-site"``; ``jobType`` is always ``"On-site"``.

No test touches the network.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_market_intel.cleaning.timesjobs_in_cleaner import TimesjobsCleaner
from job_market_intel.scrapers.timesjobs_in.client import detail_token
from job_market_intel.scrapers.timesjobs_in.config import TimesjobsSettings
from job_market_intel.scrapers.timesjobs_in.models import RawTimesjobsJob
from job_market_intel.scrapers.timesjobs_in.parser import TimesjobsParser
from job_market_intel.validation.timesjobs_in_validator import (
    TimesjobsBatchValidator,
    TimesjobsValidationSettings,
)

LISTING = {
    "applicationCount": 0,
    "loginId": 8429082,
    "companyLogo": "https://timesjob.s3.ap-south-1.amazonaws.com/company-logos/logo.svg",
    "description": "Company Overview Incedo Is A US-based Consulting Firm With 3000 People...",
    "source": "srp",
    "title": "Career Opportunities: Associate (50770)",
    "lowSalary": -1,
    "jobDetailUrl": (
        "https://www.timesjobs.com/job-detail/career-opportunities-associate-50770"
        "-incedo-mexico-1-3-years-jobid-m3yCaVX6MydzpSvf+uAgZw==&source=srp"
    ),
    "skills": "Financial Analysis   Microsoft Excel Proficiency",
    "experienceTo": 3,
    "expiryDate": "2027-01-17",
    "jobId": "81077785",
    "jobFunction": "Finance",
    "highSalary": -1,
    "postDate": "2026-11-19",
    "company": "Incedo",
    "location": "Mexico",
    "currency": "INR",
    "jobType": "On-site",
    "experienceFrom": 1,
}

DETAIL = {
    "jobId": 81077785,
    "title": "Career Opportunities: Associate (50770)",
    "description": "<strong>Company Overview</strong><p>Incedo is a US-based firm.</p>",
    "desiredCandidate": "<p>Strong analytical skills.</p>",
    "industryNames": [],
    "functionNames": ["Finance"],
    "aosNames": ["Other Accounting"],
    "roleNames": [],
    "locationNames": ["Mexico"],
    "locationOthers": "",
    "minCtc": -1,
    "maxCtc": -1,
    "ctcCurrency": "r",
    "hideCtcFromCandidate": True,
    "minExperience": 1,
    "maxExperience": 3,
    "perks": "",
    "postedAt": "2026-11-19T22:49:34",
    "postedAtFormatted": "19 Nov, 2026",
    "expiresAt": "2027-01-17",
    "employmentType": "Full-time",
    "jobType": "On-site",
    "skills": "Financial Analysis   Microsoft Excel Proficiency",
    "vacancies": 0,
    "externalJobsLink": "https://career44.sapsf.com/career?company=incedotech",
    "companyName": "Incedo",
    "companyLogo": None,
    "graduationCourseNames": ["B.Com. (Commerce)"],
    "postgraduationCourseNames": ["Any Postgraduate"],
}


def _raw(listing: dict | None = None, detail: dict | None = DETAIL) -> dict:
    listing = LISTING if listing is None else listing
    return {"url": listing.get("jobDetailUrl", ""), "listing": listing, "detail": detail}


class TestDetailToken:
    def test_extracts_and_quotes_after_jobid(self) -> None:
        token = detail_token(LISTING["jobDetailUrl"])
        # The token is everything after "jobid-", quoted as one path segment
        # (the literal "+" and "==" must be percent-encoded).
        assert token == "m3yCaVX6MydzpSvf%2BuAgZw%3D%3D%26source%3Dsrp"

    def test_none_when_marker_absent(self) -> None:
        assert detail_token("https://www.timesjobs.com/job-detail/no-token-here") is None

    def test_none_when_url_missing(self) -> None:
        assert detail_token(None) is None


class TestModels:
    def test_from_payload_merges_listing_and_detail(self) -> None:
        job = RawTimesjobsJob.from_payload(LISTING, DETAIL, original_url=LISTING["jobDetailUrl"])
        assert job.source_job_id == "81077785"
        assert job.job_title == "Career Opportunities: Associate (50770)"
        assert job.company_name == "Incedo"
        assert job.location_text == "Mexico"
        assert job.skills_raw == ["Financial Analysis", "Microsoft Excel Proficiency"]
        assert job.employment_type_raw == "Full-time"
        assert job.work_mode_raw == "On-site"
        assert job.experience_years_min == 1
        assert job.experience_years_max == 3
        assert job.function_raws == ["Finance", "Other Accounting"]
        assert job.education_raws == ["B.Com. (Commerce)", "Any Postgraduate"]
        assert job.salary_show_flag is False
        assert job.apply_url == "https://career44.sapsf.com/career?company=incedotech"
        assert job.posting_date is not None and job.posting_date.year == 2026

    def test_from_payload_listing_only_falls_back(self) -> None:
        job = RawTimesjobsJob.from_payload(LISTING, None, original_url=LISTING["jobDetailUrl"])
        assert job.source_job_id == "81077785"
        assert job.job_title == LISTING["title"]
        assert job.company_name == "Incedo"
        assert job.location_text == "Mexico"  # listing.location fallback
        assert job.employment_type_raw is None  # detail-only field

    def test_from_payload_rejects_non_object_listing(self) -> None:
        with pytest.raises(ValueError):
            RawTimesjobsJob.from_payload([], DETAIL, original_url="https://x/")

    def test_missing_title_is_rejected(self) -> None:
        listing = {**LISTING, "title": ""}
        detail = {**DETAIL, "title": ""}
        with pytest.raises(ValidationError):
            RawTimesjobsJob.from_payload(listing, detail, original_url="https://x/")

    def test_missing_job_id_is_rejected(self) -> None:
        listing = {**LISTING, "jobId": ""}
        detail = {**DETAIL, "jobId": ""}
        with pytest.raises(ValidationError):
            RawTimesjobsJob.from_payload(listing, detail, original_url="https://x/")


class TestParser:
    def test_parses_valid_and_skips_malformed(self) -> None:
        parser = TimesjobsParser()
        raw = [
            _raw(),
            {"url": "", "listing": None, "detail": None},  # malformed: no listing
            {"url": "https://x/", "listing": {**LISTING, "jobId": ""}, "detail": None},
        ]
        jobs = parser.parse_jobs(raw)
        assert len(jobs) == 1
        assert jobs[0].source_job_id == "81077785"


class TestCleaner:
    def test_hidden_salary_is_undisclosed(self) -> None:
        job = RawTimesjobsJob.from_payload(LISTING, DETAIL, original_url=LISTING["jobDetailUrl"])
        cleaned = TimesjobsCleaner().clean_job(job)
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False
        assert cleaned.currency_iso_code == "INR"
        assert cleaned.pay_period == "yearly"
        assert cleaned.employment_type_code == "full_time"
        assert cleaned.remote_work_type_code == "on_site"
        assert cleaned.experience_years_min == 1
        assert cleaned.experience_years_max == 3
        assert cleaned.apply_url == DETAIL["externalJobsLink"]
        assert "financial analysis" in cleaned.skills
        assert "finance" in cleaned.skills
        assert "US-based firm" in (cleaned.description_clean or "")

    def test_positive_salary_is_kept(self) -> None:
        detail = {**DETAIL, "hideCtcFromCandidate": False, "minCtc": 500000, "maxCtc": 800000}
        job = RawTimesjobsJob.from_payload(LISTING, detail, original_url=LISTING["jobDetailUrl"])
        cleaned = TimesjobsCleaner().clean_job(job)
        assert cleaned.salary_min == 500000
        assert cleaned.salary_max == 800000
        assert cleaned.salary_disclosed is True

    def test_reversed_salary_is_swapped(self) -> None:
        detail = {**DETAIL, "hideCtcFromCandidate": False, "minCtc": 900000, "maxCtc": 100000}
        job = RawTimesjobsJob.from_payload(LISTING, detail, original_url=LISTING["jobDetailUrl"])
        cleaned = TimesjobsCleaner().clean_job(job)
        assert cleaned.salary_min == 100000
        assert cleaned.salary_max == 900000

    def test_work_mode_word_in_employment_slot_is_ignored(self) -> None:
        detail = {**DETAIL, "employmentType": "On-site"}
        job = RawTimesjobsJob.from_payload(LISTING, detail, original_url=LISTING["jobDetailUrl"])
        cleaned = TimesjobsCleaner().clean_job(job)
        assert cleaned.employment_type_code is None

    def test_unknown_employment_type_leaves_none(self) -> None:
        detail = {**DETAIL, "employmentType": "Volunteer-ish"}
        job = RawTimesjobsJob.from_payload(LISTING, detail, original_url=LISTING["jobDetailUrl"])
        cleaned = TimesjobsCleaner().clean_job(job)
        assert cleaned.employment_type_code is None

    def test_clean_jobs_batch(self) -> None:
        job = RawTimesjobsJob.from_payload(LISTING, DETAIL, original_url=LISTING["jobDetailUrl"])
        cleaned = TimesjobsCleaner().clean_jobs([job, job])
        assert len(cleaned) == 2


class TestValidator:
    def _jobs(self, n: int) -> list[RawTimesjobsJob]:
        return [
            RawTimesjobsJob.from_payload(
                {**LISTING, "jobId": str(81070000 + i)},
                DETAIL,
                original_url=f"{LISTING['jobDetailUrl']}-{i}",
            )
            for i in range(n)
        ]

    def test_healthy_batch_passes(self) -> None:
        jobs = self._jobs(60)
        report = TimesjobsBatchValidator().validate(list(jobs), jobs)
        assert report.passed is True
        assert report.total_parsed == 60

    def test_too_few_jobs_fails(self) -> None:
        jobs = self._jobs(3)
        report = TimesjobsBatchValidator().validate(list(jobs), jobs)
        assert report.passed is False
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_zero_raw_records_fails(self) -> None:
        report = TimesjobsBatchValidator().validate([], [])
        assert report.passed is False

    def test_duplicate_ids_are_flagged(self) -> None:
        jobs = self._jobs(60)
        report = TimesjobsBatchValidator().validate(list(jobs), jobs + [jobs[0]])
        assert report.passed is False
        assert report.duplicate_source_job_ids == ["81070000"]

    def test_default_thresholds(self) -> None:
        settings = TimesjobsValidationSettings()
        assert settings.min_expected_jobs == 50
        assert settings.max_skip_rate == 0.10


class TestSettings:
    def test_defaults(self) -> None:
        settings = TimesjobsSettings()
        assert settings.page_size == 100
        assert settings.max_jobs_per_run == 200
        assert settings.list_url.endswith("/search/api/v1/search/jobs/list")
        assert "{token}" in settings.detail_url_template
        assert settings.user_agent.startswith("Mozilla/5.0")
