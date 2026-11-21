"""Unit tests for the BLMIS (www.blmis.gov.bt) scraper.

Pinned measured facts (2026-11-21, live site):

  * The whole inventory is server-rendered into the Livewire
    ``wire:initial-data`` attribute of the public jobseeker page
    ``https://www.blmis.gov.bt/jobseeker_page/mispage`` -- a single,
    keyless, no-login GET. ``serverMemo.data`` carries six overlapping
    ``job_by_*`` facets whose union was 442 unique ``application_no``
    values at scoping.
  * ``application_no`` is the stable ``source_job_id`` and the public
    detail page is
    ``https://www.blmis.gov.bt/jobseeker_page/jobdetails/<id>``.
  * ``robots.txt`` (HTTP 200) is a bare ``User-agent: *`` group with an
    EMPTY ``Disallow`` (allow-all).
  * ``starting_salary`` is a single monthly figure (no range, no currency
    code); ``employment_type`` is prose ("Regular"/"Contract");
    ``dzongkhag_name`` is the district; ``vacancy_type_id`` 516 marks an
    overseas posting whose destination sits in ``placement``.

No test touches the network.
"""

from __future__ import annotations

import html
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from job_market_intel.cleaning.blmis_bt_cleaner import BlmisCleaner
from job_market_intel.scrapers.blmis_bt.client import BlmisClient
from job_market_intel.scrapers.blmis_bt.config import BlmisSettings
from job_market_intel.scrapers.blmis_bt.exceptions import BlmisResponseError
from job_market_intel.scrapers.blmis_bt.models import RawBlmisJob
from job_market_intel.scrapers.blmis_bt.parser import BlmisParser
from job_market_intel.validation.blmis_bt_validator import (
    BlmisBatchValidator,
    BlmisValidationSettings,
)

DOMESTIC = {
    "application_no": "42015747",
    "employer_app_id": "31011800",
    "job_category_id": 1126,
    "designation": "Account Assistant",
    "qualification_id": 2014,
    "field_of_study": 1463,
    "year_of_experience": 518,
    "gewog_id": 17,
    "placement": "Meto Pema Hotel",
    "starting_salary": "16000.00",
    "slot": 1,
    "job_description": "Account assistant for entry of daily transaction",
    "employment_type": "Regular",
    "last_date_registration": "2026-12-10",
    "remarks": "Needed staff based on Phuentsholing",
    "vacancy_type_id": 185,
    "country_id": None,
    "is_deleted": "N",
    "created_at": "2026-11-19 09:23:25",
    "qualification": "Diploma",
    "job_category": "Account Officer",
    "gewog_name": "Phuntsholing Throm",
    "dzongkhag_name": "Chukha",
    "company_id": "31011800",
    "company_name": None,
    "country": None,
    "business_name": " Meto Pema Hotel",
}

OVERSEA = {
    "application_no": "43000288",
    "employer_app_id": "3131605",
    "job_category_id": 2396,
    "designation": "Coffee Maker",
    "year_of_experience": 519,
    "gewog_id": None,
    "placement": "Qatar",
    "starting_salary": "1785.00",
    "slot": 3,
    "job_description": "Responsible for preparing and serving coffee and beverages.",
    "employment_type": "Contract",
    "last_date_registration": "2026-11-23",
    "remarks": "Visit our office, MON-FRI 9-5PM. Only for Males.",
    "vacancy_type_id": 516,
    "country_id": 347,
    "is_deleted": "N",
    "created_at": "2026-11-10 10:42:33",
    "eligible_criteria": "Only for Males.\nClass 10 and above.",
    "terms_conditon": "Place of posting: Qatar\nContract period: 2 Years",
    "company_name": "Earth Organic Coffee",
    "qualification": "Class 10",
    "job_category": "Coffee Maker",
    "gewog_name": None,
    "dzongkhag_name": None,
    "company_id": "3131605",
    "country": None,
    "business_name": "Earth Organic Coffee",
}

DETAIL_URL = "https://www.blmis.gov.bt/jobseeker_page/jobdetails/42015747"


def _page(memo_data: dict) -> str:
    """Build a minimal page carrying one Livewire wire:initial-data blob."""
    payload = {
        "fingerprint": {
            "id": "IIF2uFl9ssQtJ3hPFGIQ",
            "name": "frontpage.jobseeker",
            "path": "jobseeker_page/mispage",
            "method": "GET",
            "v": "acj",
        },
        "serverMemo": {"data": memo_data},
    }
    blob = html.escape(json.dumps(payload))
    return f'<html><body><div wire:initial-data="{blob}"></div></body></html>'


class TestModels:
    def test_from_payload_domestic(self) -> None:
        job = RawBlmisJob.from_payload(DOMESTIC, original_url=DETAIL_URL)
        assert job.source_job_id == "42015747"
        assert job.job_title == "Account Assistant"
        assert job.company_name == "Meto Pema Hotel"  # business_name, trimmed
        assert job.location_text == "Phuntsholing Throm, Chukha"
        assert job.qualification_raw == "Diploma"
        assert job.category_raw == "Account Officer"
        assert job.employment_type_raw == "Regular"
        assert job.salary_min_raw == 16000.0
        assert job.vacancies == 1
        assert job.is_oversea is False
        assert job.country_text is None
        assert job.posting_date is not None and job.posting_date.year == 2026
        assert job.closing_date is not None and job.closing_date.month == 12

    def test_from_payload_oversea_via_flag_id(self) -> None:
        job = RawBlmisJob.from_payload(OVERSEA, original_url=DETAIL_URL)
        assert job.is_oversea is True
        assert job.company_name == "Earth Organic Coffee"
        assert job.location_text == "Qatar"
        assert job.country_text == "Qatar"
        assert job.eligibility_raw is not None
        assert job.terms_raw is not None

    def test_explicit_oversea_flag_uses_placement_for_location(self) -> None:
        record = {**DOMESTIC, "vacancy_type_id": 185, "placement": "Thimphu"}
        job = RawBlmisJob.from_payload(record, original_url=DETAIL_URL, is_oversea=True)
        assert job.is_oversea is True
        assert job.location_text == "Thimphu"
        assert job.country_text == "Thimphu"

    def test_location_falls_back_to_dzongkhag_only(self) -> None:
        record = {**DOMESTIC, "gewog_name": None}
        job = RawBlmisJob.from_payload(record, original_url=DETAIL_URL)
        assert job.location_text == "Chukha"

    def test_missing_id_is_rejected(self) -> None:
        record = {**DOMESTIC, "application_no": ""}
        with pytest.raises(ValueError):
            RawBlmisJob.from_payload(record, original_url=DETAIL_URL)

    def test_missing_title_is_rejected(self) -> None:
        record = {**DOMESTIC, "designation": ""}
        with pytest.raises(ValidationError):
            RawBlmisJob.from_payload(record, original_url=DETAIL_URL)

    def test_non_object_record_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            RawBlmisJob.from_payload([], original_url=DETAIL_URL)


class TestClient:
    def test_decode_initial_data_roundtrip(self) -> None:
        page = _page({"job_by_yelp": [DOMESTIC]})
        data = BlmisClient._decode_initial_data(page)
        assert data["serverMemo"]["data"]["job_by_yelp"][0]["application_no"] == "42015747"

    def test_decode_rejects_missing_attribute(self) -> None:
        with pytest.raises(BlmisResponseError):
            BlmisClient._decode_initial_data("<html><body>no livewire here</body></html>")

    def test_decode_rejects_non_json(self) -> None:
        page = '<div wire:initial-data="not json"></div>'
        with pytest.raises(BlmisResponseError):
            BlmisClient._decode_initial_data(page)

    def test_fetch_merges_facets_and_dedups(self, monkeypatch: pytest.MonkeyPatch) -> None:
        memo = {
            "job_by_yelp": [DOMESTIC],
            "job_by_categories": [DOMESTIC],  # duplicate of the same posting
            "job_by_oversea": [OVERSEA],
        }
        client = BlmisClient(settings=BlmisSettings())
        monkeypatch.setattr(
            client,
            "_get",
            lambda url, what: SimpleNamespace(text=_page(memo)),
        )
        jobs = client.fetch_raw_jobs()
        assert len(jobs) == 2
        assert {job["id"] for job in jobs} == {"42015747", "43000288"}
        by_id = {job["id"]: job for job in jobs}
        assert by_id["42015747"]["oversea"] is False
        assert by_id["43000288"]["oversea"] is True
        assert by_id["43000288"]["url"].endswith("/43000288")

    def test_fetch_raises_on_zero_vacancies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = BlmisClient(settings=BlmisSettings())
        monkeypatch.setattr(
            client,
            "_get",
            lambda url, what: SimpleNamespace(text=_page({"job_by_yelp": []})),
        )
        with pytest.raises(BlmisResponseError):
            client.fetch_raw_jobs()


class TestParser:
    def test_parses_valid_and_skips_malformed(self) -> None:
        parser = BlmisParser()
        raw = [
            {"id": "42015747", "record": DOMESTIC, "oversea": False, "url": DETAIL_URL},
            {"id": "", "record": None, "oversea": False, "url": DETAIL_URL},
            {
                "id": "x",
                "record": {**DOMESTIC, "application_no": ""},
                "oversea": False,
                "url": DETAIL_URL,
            },
        ]
        jobs = parser.parse_jobs(raw)
        assert len(jobs) == 1
        assert jobs[0].source_job_id == "42015747"


class TestCleaner:
    def test_domestic_salary_and_mappings(self) -> None:
        job = RawBlmisJob.from_payload(DOMESTIC, original_url=DETAIL_URL)
        cleaned = BlmisCleaner().clean_job(job)
        assert cleaned.salary_min == 16000.0
        assert cleaned.salary_max is None  # single "starting_salary" figure
        assert cleaned.salary_disclosed is True
        assert cleaned.currency_iso_code == "BTN"
        assert cleaned.pay_period == "monthly"
        assert cleaned.employment_type_code == "full_time"
        assert cleaned.remote_work_type_code is None
        assert cleaned.location_cleaned == "Phuntsholing Throm, Chukha"
        assert "Account assistant" in (cleaned.description_clean or "")
        assert "Diploma" in (cleaned.description_clean or "")
        assert "Phuentsholing" in (cleaned.description_clean or "")
        assert cleaned.apply_url == DETAIL_URL

    def test_oversea_currency_and_contract(self) -> None:
        job = RawBlmisJob.from_payload(OVERSEA, original_url=DETAIL_URL)
        cleaned = BlmisCleaner().clean_job(job)
        assert cleaned.currency_iso_code == "QAR"
        assert cleaned.employment_type_code == "contract"
        assert cleaned.location_cleaned == "Qatar"
        assert cleaned.salary_min == 1785.0

    def test_zero_salary_is_undisclosed(self) -> None:
        job = RawBlmisJob.from_payload(
            {**DOMESTIC, "starting_salary": "0"}, original_url=DETAIL_URL
        )
        cleaned = BlmisCleaner().clean_job(job)
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_one_ngultrum_placeholder_is_undisclosed(self) -> None:
        # Measured live: a "sales manager" post carries starting_salary
        # "1.00", the board's "not stated" placeholder.
        job = RawBlmisJob.from_payload(
            {**DOMESTIC, "starting_salary": "1.00"}, original_url=DETAIL_URL
        )
        cleaned = BlmisCleaner().clean_job(job)
        assert cleaned.salary_min is None
        assert cleaned.salary_disclosed is False

    def test_smallest_real_salary_is_kept(self) -> None:
        job = RawBlmisJob.from_payload(
            {**DOMESTIC, "starting_salary": "2.00"}, original_url=DETAIL_URL
        )
        cleaned = BlmisCleaner().clean_job(job)
        assert cleaned.salary_min == 2.0
        assert cleaned.salary_disclosed is True

    def test_casual_freelance_is_left_unmapped(self) -> None:
        # A combined label names two engagement types at once, so no single
        # ref code is right; the raw value survives in raw_payload.
        job = RawBlmisJob.from_payload(
            {**DOMESTIC, "employment_type": "Casual/Freelance"}, original_url=DETAIL_URL
        )
        cleaned = BlmisCleaner().clean_job(job)
        assert cleaned.employment_type_code is None
        assert cleaned.raw_payload["employment_type"] == "Casual/Freelance"

    def test_unknown_employment_type_leaves_none(self) -> None:
        job = RawBlmisJob.from_payload(
            {**DOMESTIC, "employment_type": "Volunteer-ish"}, original_url=DETAIL_URL
        )
        cleaned = BlmisCleaner().clean_job(job)
        assert cleaned.employment_type_code is None

    def test_clean_jobs_batch(self) -> None:
        job = RawBlmisJob.from_payload(DOMESTIC, original_url=DETAIL_URL)
        cleaned = BlmisCleaner().clean_jobs([job, job])
        assert len(cleaned) == 2


class TestValidator:
    def _jobs(self, n: int) -> list[RawBlmisJob]:
        return [
            RawBlmisJob.from_payload(
                {**DOMESTIC, "application_no": str(42010000 + i)},
                original_url=f"https://www.blmis.gov.bt/jobseeker_page/jobdetails/{42010000 + i}",
            )
            for i in range(n)
        ]

    def test_healthy_batch_passes(self) -> None:
        jobs = self._jobs(30)
        report = BlmisBatchValidator().validate(list(jobs), jobs)
        assert report.passed is True
        assert report.total_parsed == 30

    def test_too_few_jobs_fails(self) -> None:
        jobs = self._jobs(3)
        report = BlmisBatchValidator().validate(list(jobs), jobs)
        assert report.passed is False
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_zero_raw_records_fails(self) -> None:
        report = BlmisBatchValidator().validate([], [])
        assert report.passed is False

    def test_duplicate_ids_are_flagged(self) -> None:
        jobs = self._jobs(30)
        report = BlmisBatchValidator().validate(list(jobs), jobs + [jobs[0]])
        assert report.passed is False
        assert report.duplicate_source_job_ids == ["42010000"]

    def test_default_thresholds(self) -> None:
        settings = BlmisValidationSettings()
        assert settings.min_expected_jobs == 20
        assert settings.max_skip_rate == 0.10


class TestSettings:
    def test_defaults(self) -> None:
        settings = BlmisSettings()
        assert settings.list_url == "https://www.blmis.gov.bt/jobseeker_page/mispage"
        assert settings.detail_page_base == ("https://www.blmis.gov.bt/jobseeker_page/jobdetails/")
        assert settings.max_jobs_per_run == 500
        assert settings.user_agent.startswith("Mozilla/5.0")
