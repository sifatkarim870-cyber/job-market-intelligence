"""Unit tests for the Bdjobs (bdjobs.com) scraper.

Pinned measured facts (2026-11-21, live site):

  * Discovery is ``GET
    https://api.bdjobs.com/jobs/api/v1/JobSearch/GetJobSearch`` with
    ``pg=N&rpp=100`` returning ``{message, statuscode, data[],
    premiumData[], common{total_records_found, totalpages,
    total_vacancies}}``; the whole board was ~5,747 rows over 58 pages and
    the feed is newest-first. ``data`` and ``premiumData`` are merged and
    de-duplicated by ``Jobid``.
  * Every search row is hydrated by ``GET
    https://api.bdjobs.com/jobs/api/v1/JobSubsystem/jobDetails`` with
    ``jobId=<id>&ln=1&IsCorporate=false``; no extra header is needed.
  * ``Jobid`` (search) / ``JobId`` (detail) is the stable
    ``source_job_id`` and the public detail page is
    ``https://bdjobs.com/h/details/<id>``.
  * The HTML hosts ``bdjobs.com`` / ``jobs.bdjobs.com`` both carry a
    ``User-agent: *`` group ending in ``Disallow: /``; only
    ``api.bdjobs.com`` (robots.txt HTTP 404 -> "unavailable") is fetched.
  * Salary is often undisclosed: ``ShowSalary`` is ``"0"`` on some rows,
    many disclosed rows are "Negotiable" (bounds ``0``), the rest carry
    ``"Tk. <min> - <max> (Monthly)"``. ``JobSalaryMinSalary`` /
    ``JobSalaryMaxSalary`` are whole BDT and ``0`` when unstated.
  * ``JobNature`` is usually "Full Time"; ``JobWorkPlace`` is
    "Work at office", "Work from home" or blank.

No test touches the network.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_market_intel.cleaning.bdjobs_com_cleaner import BdjobsCleaner
from job_market_intel.scrapers.bdjobs_com.config import BdjobsSettings
from job_market_intel.scrapers.bdjobs_com.models import RawBdjobsJob
from job_market_intel.scrapers.bdjobs_com.parser import BdjobsParser
from job_market_intel.validation.bdjobs_com_validator import (
    BdjobsBatchValidator,
    BdjobsValidationSettings,
)

LISTING = {
    "Jobid": "1558863",
    "AdType": "0",
    "jobTitle": "Assistant Engineer",
    "companyName": "Richman Informatics",
    "JobTitleBng": "সহকারী প্রকৌশলী",
    "deadline": "Dec 04, 2026",
    "deadlineDB": "2026-12-04T00:00:00",
    "publishDate": "2026-11-21T11:25:00Z",
    "eduRec": "BSc in Civil Engineering",
    "experience": "At least 5 years",
    "location": "Dhaka",
    "JobLang": "1",
    "jobContext": "We are looking for an Assistant Engineer.",
    "logoUrl": "https://static.bdjobs.com/logo/richman.png",
    "jobDescription": "We are looking for an Assistant Engineer.",
    "JobType": "Full Time",
    "Vacancies": "2",
    "Salary": "Tk. 20000 - 30000 (Monthly)",
    "WorkPlace": "Work at office",
    "Cat_id": "5",
}

DETAIL = {
    "test": "1",
    "JobId": "1558863",
    "JobFound": "True",
    "error": "0",
    "CompnayName": "Richman Informatics",
    "CompanyNameENG": "Richman Informatics",
    "JobTitle": "Assistant Engineer",
    "JobLOgoName": "https://static.bdjobs.com/logo/richman.png",
    "JobDescription": "<p>We are looking for an Assistant Engineer.</p>",
    "AdditionJobRequirements": "<p>Must be able to work under pressure.</p>",
    "JobOtherBenifits": "<p>Festival bonus, provident fund.</p>",
    "EducationRequirements": "<p>BSc in Civil Engineering.</p>",
    "SkillsRequired": "AutoCAD, Surveying, MS Office",
    "SuggestedSkills": "Communication, Teamwork",
    "JobLocation": "Dhaka",
    "PostedOn": "Nov 21, 2026",
    "Deadline": "Dec 04, 2026",
    "DeadlineDB": "2026-12-04",
    "JobNature": "Full Time",
    "JobWorkPlace": "Work at office",
    "JobSalaryMinSalary": "20000",
    "JobSalaryMaxSalary": "30000",
    "ShowSalary": "1",
    "JobSalaryRange": "Tk. 20000 - 30000 (Monthly)",
    "JobSalaryRangeText": "Tk. 20000 - 30000 (Monthly)",
    "experience": "<ul><li>At least 5 years</li></ul>",
    "JobVacancies": "2",
    "ApplyURL": "https://bdjobs.com/apply/1558863",
    "JobAppliedEmail": "",
}

PUBLIC_URL = "https://bdjobs.com/h/details/1558863"


def _raw(listing: dict | None = None, detail: dict | None = DETAIL) -> dict:
    listing = LISTING if listing is None else listing
    return {
        "id": listing.get("Jobid", ""),
        "url": f"https://bdjobs.com/h/details/{listing.get('Jobid', '')}",
        "listing": listing,
        "detail": detail,
    }


class TestModels:
    def test_from_payload_merges_listing_and_detail(self) -> None:
        job = RawBdjobsJob.from_payload(LISTING, DETAIL, original_url=PUBLIC_URL)
        assert job.source_job_id == "1558863"
        assert job.job_title == "Assistant Engineer"
        assert job.company_name == "Richman Informatics"
        assert job.location_text == "Dhaka"
        assert job.skills_raw == [
            "AutoCAD",
            "Surveying",
            "MS Office",
            "Communication",
            "Teamwork",
        ]
        assert job.employment_type_raw == "Full Time"
        assert job.work_mode_raw == "Work at office"
        assert job.salary_min_raw == 20000
        assert job.salary_max_raw == 30000
        assert job.salary_show_flag is True
        assert job.apply_url == "https://bdjobs.com/apply/1558863"
        assert job.posting_date is not None and job.posting_date.year == 2026
        assert job.closing_date is not None and job.closing_date.month == 12

    def test_from_payload_listing_only_falls_back(self) -> None:
        job = RawBdjobsJob.from_payload(LISTING, None, original_url=PUBLIC_URL)
        assert job.source_job_id == "1558863"
        assert job.job_title == LISTING["jobTitle"]
        assert job.company_name == LISTING["companyName"]
        assert job.location_text == "Dhaka"  # listing.location fallback
        assert job.employment_type_raw == "Full Time"  # listing.JobType fallback
        assert job.work_mode_raw == "Work at office"  # listing.WorkPlace fallback
        assert job.description_html is None  # detail-only field
        assert job.salary_min_raw is None  # detail-only field
        assert job.salary_show_flag is None

    def test_from_payload_builds_mailto_when_only_email_given(self) -> None:
        detail = {**DETAIL, "ApplyURL": "", "JobAppliedEmail": "hr@richman.com.bd"}
        job = RawBdjobsJob.from_payload(LISTING, detail, original_url=PUBLIC_URL)
        assert job.apply_url == "mailto:hr@richman.com.bd"

    def test_from_payload_rejects_non_object_listing(self) -> None:
        with pytest.raises(ValueError):
            RawBdjobsJob.from_payload([], DETAIL, original_url=PUBLIC_URL)

    def test_missing_title_is_rejected(self) -> None:
        listing = {**LISTING, "jobTitle": ""}
        detail = {**DETAIL, "JobTitle": ""}
        with pytest.raises(ValidationError):
            RawBdjobsJob.from_payload(listing, detail, original_url=PUBLIC_URL)

    def test_missing_job_id_is_rejected(self) -> None:
        listing = {**LISTING, "Jobid": ""}
        detail = {**DETAIL, "JobId": ""}
        with pytest.raises(ValueError):
            RawBdjobsJob.from_payload(listing, detail, original_url=PUBLIC_URL)


class TestParser:
    def test_parses_valid_and_skips_malformed(self) -> None:
        parser = BdjobsParser()
        raw = [
            _raw(),
            {"id": "", "url": PUBLIC_URL, "listing": None, "detail": None},
            {"id": "x", "url": PUBLIC_URL, "listing": {**LISTING, "Jobid": ""}, "detail": None},
        ]
        jobs = parser.parse_jobs(raw)
        assert len(jobs) == 1
        assert jobs[0].source_job_id == "1558863"


class TestCleaner:
    def test_disclosed_salary_and_mappings(self) -> None:
        job = RawBdjobsJob.from_payload(LISTING, DETAIL, original_url=PUBLIC_URL)
        cleaned = BdjobsCleaner().clean_job(job)
        assert cleaned.salary_min == 20000
        assert cleaned.salary_max == 30000
        assert cleaned.salary_disclosed is True
        assert cleaned.currency_iso_code == "BDT"
        assert cleaned.pay_period == "monthly"
        assert cleaned.employment_type_code == "full_time"
        assert cleaned.remote_work_type_code == "on_site"
        assert cleaned.experience_years_min == 5
        assert cleaned.experience_years_max is None
        assert cleaned.apply_url == DETAIL["ApplyURL"]
        assert "autocad" in cleaned.skills
        assert "communication" in cleaned.skills
        assert "Assistant Engineer" in (cleaned.description_clean or "")
        assert "Festival bonus" in (cleaned.description_clean or "")

    def test_show_salary_zero_forces_undisclosed(self) -> None:
        detail = {**DETAIL, "ShowSalary": "0"}
        job = RawBdjobsJob.from_payload(LISTING, detail, original_url=PUBLIC_URL)
        cleaned = BdjobsCleaner().clean_job(job)
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_negotiable_zero_bounds_are_undisclosed(self) -> None:
        detail = {
            **DETAIL,
            "JobSalaryMinSalary": "0",
            "JobSalaryMaxSalary": "0",
            "JobSalaryRange": "Negotiable",
            "ShowSalary": "1",
        }
        job = RawBdjobsJob.from_payload(LISTING, detail, original_url=PUBLIC_URL)
        cleaned = BdjobsCleaner().clean_job(job)
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_reversed_salary_is_swapped(self) -> None:
        detail = {**DETAIL, "JobSalaryMinSalary": "90000", "JobSalaryMaxSalary": "10000"}
        job = RawBdjobsJob.from_payload(LISTING, detail, original_url=PUBLIC_URL)
        cleaned = BdjobsCleaner().clean_job(job)
        assert cleaned.salary_min == 10000
        assert cleaned.salary_max == 90000

    def test_work_from_home_maps_to_remote_country(self) -> None:
        detail = {**DETAIL, "JobWorkPlace": "Work from home"}
        job = RawBdjobsJob.from_payload(LISTING, detail, original_url=PUBLIC_URL)
        cleaned = BdjobsCleaner().clean_job(job)
        assert cleaned.remote_work_type_code == "remote_country"

    def test_contractual_nature_maps_to_contract(self) -> None:
        detail = {**DETAIL, "JobNature": "Contractual"}
        job = RawBdjobsJob.from_payload(LISTING, detail, original_url=PUBLIC_URL)
        cleaned = BdjobsCleaner().clean_job(job)
        assert cleaned.employment_type_code == "contract"

    def test_unknown_employment_type_leaves_none(self) -> None:
        detail = {**DETAIL, "JobNature": "Volunteer-ish"}
        job = RawBdjobsJob.from_payload(LISTING, detail, original_url=PUBLIC_URL)
        cleaned = BdjobsCleaner().clean_job(job)
        assert cleaned.employment_type_code is None

    def test_experience_range_is_parsed(self) -> None:
        detail = {**DETAIL, "experience": "<ul><li>3 to 5 years</li></ul>"}
        job = RawBdjobsJob.from_payload(LISTING, detail, original_url=PUBLIC_URL)
        cleaned = BdjobsCleaner().clean_job(job)
        assert cleaned.experience_years_min == 3
        assert cleaned.experience_years_max == 5

    def test_clean_jobs_batch(self) -> None:
        job = RawBdjobsJob.from_payload(LISTING, DETAIL, original_url=PUBLIC_URL)
        cleaned = BdjobsCleaner().clean_jobs([job, job])
        assert len(cleaned) == 2


class TestValidator:
    def _jobs(self, n: int) -> list[RawBdjobsJob]:
        return [
            RawBdjobsJob.from_payload(
                {**LISTING, "Jobid": str(1558000 + i)},
                {**DETAIL, "JobId": str(1558000 + i)},
                original_url=f"https://bdjobs.com/h/details/{1558000 + i}",
            )
            for i in range(n)
        ]

    def test_healthy_batch_passes(self) -> None:
        jobs = self._jobs(30)
        report = BdjobsBatchValidator().validate(list(jobs), jobs)
        assert report.passed is True
        assert report.total_parsed == 30

    def test_too_few_jobs_fails(self) -> None:
        jobs = self._jobs(3)
        report = BdjobsBatchValidator().validate(list(jobs), jobs)
        assert report.passed is False
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_zero_raw_records_fails(self) -> None:
        report = BdjobsBatchValidator().validate([], [])
        assert report.passed is False

    def test_duplicate_ids_are_flagged(self) -> None:
        jobs = self._jobs(30)
        report = BdjobsBatchValidator().validate(list(jobs), jobs + [jobs[0]])
        assert report.passed is False
        assert report.duplicate_source_job_ids == ["1558000"]

    def test_default_thresholds(self) -> None:
        settings = BdjobsValidationSettings()
        assert settings.min_expected_jobs == 20
        assert settings.max_skip_rate == 0.10


class TestSettings:
    def test_defaults(self) -> None:
        settings = BdjobsSettings()
        assert settings.search_url.endswith("/api/v1/JobSearch/GetJobSearch")
        assert settings.detail_url.endswith("/api/v1/JobSubsystem/jobDetails")
        assert settings.detail_page_base == "https://bdjobs.com/h/details/"
        assert settings.rows_per_page == 100
        assert settings.max_jobs_per_run == 200
        assert settings.user_agent.startswith("Mozilla/5.0")
