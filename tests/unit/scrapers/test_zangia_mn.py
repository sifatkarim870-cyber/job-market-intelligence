"""Unit tests for the Zangia (zangia.mn) scraper.

Pinned measured facts (2026-11-21, live site):

  * Discovery is ``GET
    https://hr-api.zangia.mn/api/job/public/list/search`` returning
    ``{data, page, limit, total, totalPages}``; the default page size is 90,
    ``limit`` accepts at least 500, and the feed is newest-first by
    ``sortTime``.
  * Every listing row is hydrated by ``GET
    https://hr-api.zangia.mn/api/job/public/detail/<code>`` where ``code``
    is the listing slug; the public page is ``https://zangia.mn/job/<code>``.
  * ``sortTime``/``time`` is the only timestamp (epoch seconds; 1795048621
    -> 2026-11-19T01:15:02Z) and ``isFeatured`` is *not* a posting date.
  * ``salary`` is always populated, in whole MNT, quoted monthly.
  * ``timetype.name_en`` is observed as "Full-time" or "Shift" (Shift is a
    schedule, not an employment type).

No test touches the network.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_market_intel.cleaning.zangia_mn_cleaner import ZangiaCleaner
from job_market_intel.scrapers.zangia_mn.config import ZangiaSettings
from job_market_intel.scrapers.zangia_mn.models import RawZangiaJob
from job_market_intel.scrapers.zangia_mn.parser import ZangiaParser
from job_market_intel.validation.zangia_mn_validator import (
    ZangiaBatchValidator,
    ZangiaValidationSettings,
)

LISTING = {
    "id": "1246071",
    "code": "4yr4tnp5cm",
    "title": "Нярав",
    "mlevel": 2,
    "isFeatured": 1795480738,
    "forHbi": 0,
    "changeable": 0,
    "sortTime": 1795048621,
    "cvCnt": 14,
    "lat": 47.94995449,
    "lng": 106.96465015,
    "company": {
        "id": 11414,
        "name": "Ариранг Фүүдс ХХК",
        "logo": "F1-3DLSQLT-SB4QTZ6-T810AKI-0F",
        "alias": "Arirang-Foods-LLC",
        "branch": "Энгийн ажил мэргэжил, үйлчилгээ",
    },
    "salary": {"id": 5, "phrase": "1,800,000-2,100,000", "min": 1800000, "max": 2100000},
    "timeSalary": 0,
    "timetype": 1,
    "location": "Баянзүрх дүүрэг",
}

DETAIL = {
    "id": "1246071",
    "code": "4yr4tnp5cm",
    "title": "Нярав",
    "mlevel": 2,
    "sortTime": 1795048621,
    "salary": {"id": 5, "phrase": "1,800,000-2,100,000", "min": 1800000, "max": 2100000},
    "location": "Баянзүрх дүүрэг",
    "isEnglish": 0,
    "isActive": True,
    "isArchive": False,
    "description": "<ul><li><p>7/7 хоног ээлжээр ажиллана.</p></li></ul><p></p>",
    "requirements": "<ul><li><p>Няраваар ажиллаж байсан туршлага</p></li></ul>",
    "additional": "<ul><li><p>Өдрийн хоол.</p></li></ul>",
    "skills": [
        {"id": 13, "name_mn": "Цагийн менежмент", "name_en": "Time Management", "cat_id": 1},
        {"id": 27, "name_mn": "Нягт нямбай", "name_en": "Attention to Detail", "cat_id": 1},
        {"id": 50, "name_mn": "Харилцааны чадвар", "name_en": "Communication", "cat_id": 1},
        {"id": 145, "name_mn": "Зохион байгуулалт", "name_en": "Organization", "cat_id": 1},
        {
            "id": 1746,
            "name_mn": "Санхүүгийн программ хангамж",
            "name_en": "Financial Software",
            "cat_id": 6,
        },
    ],
    "benefits": [],
    "branch": {"id": 14, "name_mn": "Банк, санхүү", "name_en": "Bank, Finance and Accounting"},
    "jobLevel": {"id": 2, "name_mn": "Ажилтан", "name_en": "Employee"},
    "timeSalary": 0,
    "time": 1795048621,
    "address": "Баянзүрх дүүрэг 5 хороо",
    "contact": "86616633",
    "applies": 14,
    "timetype": {"id": 1, "name_mn": "Бүтэн цагийн", "name_en": "Full-time"},
    "company": {
        "id": 11414,
        "alias": "Arirang-Foods-LLC",
        "name": "Ариранг Фүүдс ХХК",
        "mlevel": 2,
        "logo": "F1-3DLSQLT-SB4QTZ6-T810AKI-0F",
        "website": "",
        "facebook": "https://www.facebook.com/Arirang.mn",
    },
}


def _raw(listing: dict | None = None, detail: dict | None = DETAIL) -> dict:
    listing = LISTING if listing is None else listing
    code = listing.get("code", "")
    return {"url": f"https://zangia.mn/job/{code}", "listing": listing, "detail": detail}


class TestModels:
    def test_from_payload_merges_listing_and_detail(self) -> None:
        job = RawZangiaJob.from_payload(
            LISTING, DETAIL, original_url="https://zangia.mn/job/4yr4tnp5cm"
        )
        assert job.source_job_id == "4yr4tnp5cm"
        assert job.job_title == "Нярав"
        assert job.company_name == "Ариранг Фүүдс ХХК"
        assert job.company_logo_url is None
        assert job.location_text == "Баянзүрх дүүрэг"
        assert job.employment_type_raw == "Full-time"
        assert job.salary_min_raw == 1800000
        assert job.salary_max_raw == 2100000
        assert job.skills_raw == [
            "Time Management",
            "Attention to Detail",
            "Communication",
            "Organization",
            "Financial Software",
        ]
        assert job.posting_date is not None
        assert (job.posting_date.year, job.posting_date.month) == (2026, 11)
        assert job.description_html is not None and job.description_html.startswith("<ul>")
        assert job.original_url == "https://zangia.mn/job/4yr4tnp5cm"

    def test_from_payload_listing_only_falls_back(self) -> None:
        job = RawZangiaJob.from_payload(
            LISTING, None, original_url="https://zangia.mn/job/4yr4tnp5cm"
        )
        assert job.source_job_id == "4yr4tnp5cm"
        assert job.job_title == LISTING["title"]
        assert job.company_name == LISTING["company"]["name"]
        assert job.location_text == "Баянзүрх дүүрэг"  # listing.location fallback
        assert job.salary_min_raw == 1800000  # listing.salary fallback
        assert job.employment_type_raw is None  # detail-only field
        assert job.description_html is None

    def test_from_payload_rejects_non_object_listing(self) -> None:
        with pytest.raises(ValueError):
            RawZangiaJob.from_payload([], DETAIL, original_url="https://x/")

    def test_missing_title_is_rejected(self) -> None:
        listing = {**LISTING, "title": ""}
        detail = {**DETAIL, "title": ""}
        with pytest.raises(ValidationError):
            RawZangiaJob.from_payload(listing, detail, original_url="https://x/")

    def test_missing_code_is_rejected(self) -> None:
        listing = {**LISTING, "code": ""}
        detail = {**DETAIL, "code": ""}
        with pytest.raises(ValidationError):
            RawZangiaJob.from_payload(listing, detail, original_url="https://x/")

    def test_mongolian_only_skill_name_is_used_when_english_absent(self) -> None:
        detail = {
            **DETAIL,
            "skills": [{"id": 1, "name_mn": "Монгол чадвар", "name_en": ""}],
        }
        job = RawZangiaJob.from_payload(LISTING, detail, original_url="https://x/")
        assert job.skills_raw == ["Монгол чадвар"]


class TestParser:
    def test_parses_valid_and_skips_malformed(self) -> None:
        parser = ZangiaParser()
        raw = [
            _raw(),
            {"url": "", "listing": None, "detail": None},  # malformed: no listing
            {"url": "https://x/", "listing": {**LISTING, "code": ""}, "detail": None},
        ]
        jobs = parser.parse_jobs(raw)
        assert len(jobs) == 1
        assert jobs[0].source_job_id == "4yr4tnp5cm"


class TestCleaner:
    def test_salary_and_currency(self) -> None:
        job = RawZangiaJob.from_payload(LISTING, DETAIL, original_url="https://x/")
        cleaned = ZangiaCleaner().clean_job(job)
        assert cleaned.salary_min == 1800000
        assert cleaned.salary_max == 2100000
        assert cleaned.salary_disclosed is True
        assert cleaned.currency_iso_code == "MNT"
        assert cleaned.pay_period == "monthly"
        assert cleaned.employment_type_code == "full_time"
        assert cleaned.remote_work_type_code is None
        assert "time management" in cleaned.skills
        assert "7/7" in (cleaned.description_clean or "")

    def test_zero_bound_is_undisclosed(self) -> None:
        detail = {**DETAIL, "salary": {"id": 1, "phrase": "", "min": 0, "max": 0}}
        job = RawZangiaJob.from_payload(LISTING, detail, original_url="https://x/")
        cleaned = ZangiaCleaner().clean_job(job)
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_single_bound_is_disclosed(self) -> None:
        detail = {**DETAIL, "salary": {"id": 1, "phrase": "1,000,000", "min": 1000000, "max": 0}}
        job = RawZangiaJob.from_payload(LISTING, detail, original_url="https://x/")
        cleaned = ZangiaCleaner().clean_job(job)
        assert cleaned.salary_min == 1000000
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is True

    def test_reversed_salary_is_swapped(self) -> None:
        detail = {**DETAIL, "salary": {"id": 1, "phrase": "", "min": 3000000, "max": 1000000}}
        job = RawZangiaJob.from_payload(LISTING, detail, original_url="https://x/")
        cleaned = ZangiaCleaner().clean_job(job)
        assert cleaned.salary_min == 1000000
        assert cleaned.salary_max == 3000000

    def test_shift_timetype_is_not_an_employment_type(self) -> None:
        detail = {**DETAIL, "timetype": {"id": 3, "name_mn": "Ээлж", "name_en": "Shift"}}
        job = RawZangiaJob.from_payload(LISTING, detail, original_url="https://x/")
        cleaned = ZangiaCleaner().clean_job(job)
        assert cleaned.employment_type_code is None

    def test_unknown_employment_type_leaves_none(self) -> None:
        detail = {**DETAIL, "timetype": {"id": 9, "name_mn": "", "name_en": "Volunteer-ish"}}
        job = RawZangiaJob.from_payload(LISTING, detail, original_url="https://x/")
        cleaned = ZangiaCleaner().clean_job(job)
        assert cleaned.employment_type_code is None

    def test_clean_jobs_batch(self) -> None:
        job = RawZangiaJob.from_payload(LISTING, DETAIL, original_url="https://x/")
        cleaned = ZangiaCleaner().clean_jobs([job, job])
        assert len(cleaned) == 2


class TestValidator:
    def _jobs(self, n: int) -> list[RawZangiaJob]:
        return [
            RawZangiaJob.from_payload(
                {**LISTING, "code": f"code{i:04d}"},
                DETAIL,
                original_url=f"https://zangia.mn/job/code{i:04d}",
            )
            for i in range(n)
        ]

    def test_healthy_batch_passes(self) -> None:
        jobs = self._jobs(60)
        report = ZangiaBatchValidator().validate(list(jobs), jobs)
        assert report.passed is True
        assert report.total_parsed == 60

    def test_too_few_jobs_fails(self) -> None:
        jobs = self._jobs(3)
        report = ZangiaBatchValidator().validate(list(jobs), jobs)
        assert report.passed is False
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_zero_raw_records_fails(self) -> None:
        report = ZangiaBatchValidator().validate([], [])
        assert report.passed is False

    def test_duplicate_ids_are_flagged(self) -> None:
        jobs = self._jobs(60)
        report = ZangiaBatchValidator().validate(list(jobs), jobs + [jobs[0]])
        assert report.passed is False
        assert report.duplicate_source_job_ids == ["code0000"]

    def test_default_thresholds(self) -> None:
        settings = ZangiaValidationSettings()
        assert settings.min_expected_jobs == 50
        assert settings.max_skip_rate == 0.10


class TestSettings:
    def test_defaults(self) -> None:
        settings = ZangiaSettings()
        assert settings.page_size == 90
        assert settings.max_jobs_per_run == 200
        assert settings.list_url.endswith("/job/public/list/search")
        assert "{code}" in settings.detail_url_template
        assert settings.user_agent.startswith("Mozilla/5.0")
