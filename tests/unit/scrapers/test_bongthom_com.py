"""Unit tests for the BongThom (bongthom.com) scraper.

Pinned measured facts (2026-11-21, live site):

  * Discovery is ``GET
    https://bongthom.com/Job_Controller/get_all?page=N`` returning the
    board's Laravel paginator envelope (``{current_page, data[], last_page,
    per_page, total, ...}``); the whole board was 278 jobs over 7 pages and
    the feed is newest-first.
  * Structured detail is ``GET
    https://bongthom.com/Job_Controller/get_embed/<id>``; rendered detail is
    ``GET https://bongthom.com/job_detail/view_detail_<id>.html``.
  * ``id`` is the stable ``source_job_id`` and the public page is
    ``https://bongthom.com/job_detail/view_detail_<id>.html``.
  * ``robots.txt`` (HTTP 200) serves the application's HTML page under
    ``text/html`` rather than a policy file, so there is no policy to obey.
  * Salary is a ``$`` figure (``"$350 - $450 Negotiable"``) or a
    "Negotiable"/"Based on Experience"/"N/A"/"Other Benefits" label;
    ``Schedule:`` is "Full-time"/"Part-time"/"Short-term"; every label/value
    row is a ``li.clearfix.en`` even when the page renders Khmer, so the
    parser keeps only rows whose label is a known English label.

No test touches the network.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from job_market_intel.cleaning.bongthom_com_cleaner import (
    BongthomCleaner,
    parse_salary,
)
from job_market_intel.scrapers.bongthom_com.client import BongthomClient
from job_market_intel.scrapers.bongthom_com.config import BongthomSettings
from job_market_intel.scrapers.bongthom_com.exceptions import BongthomResponseError
from job_market_intel.scrapers.bongthom_com.models import RawBongthomJob
from job_market_intel.scrapers.bongthom_com.parser import BongthomParser
from job_market_intel.validation.bongthom_com_validator import (
    BongthomBatchValidator,
    BongthomValidationSettings,
)

LISTING = {
    "id": 42739,
    "title": "Sales Manager",
    "company": "H O S Trading Co.Ltd.",
    "logo": "https://bongsrey.sgp1.digitaloceanspaces.com/images/error_pic.jpg",
    "start_date": "2026-11-21 02:24:29",
    "close_date": "2026-12-20 00:00:00",
}

EMBED = {
    "id": 42739,
    "title": "Sales Manager",
    "company": "H O S Trading Co.Ltd.",
    "logo": "https://bongsrey.sgp1.digitaloceanspaces.com/images/error_pic.jpg",
    "start_date": "2026-11-21 02:24:29",
    "close_date": "2026-12-20 00:00:00",
    "positions": [
        {
            "id": 51001,
            "title": "Sales Manager",
            "description": "<p>We are now looking for a qualified candidate.</p>",
            "duties": [
                {"text": "Visit assigned outlets daily."},
                {"text": "Prepare weekly reports."},
            ],
            "benefits": [{"benefit": "International mentoring and professional development."}],
            "qualifications": [{"major": "Business Administration"}],
            "experiences": [
                {"years": 3, "position": "sales management experience"},
                {"years": 5, "position": "team leadership experience"},
            ],
            "skill_knowledges": [
                {"skill": "Negotiation", "skill_type": "hard"},
                {"skill": "English", "skill_type": "language"},
                {"skill": "Negotiation", "skill_type": "hard"},
            ],
            "categories": [{"name_en": "Sales / Marketing"}],
        }
    ],
}

WORKPLACE = {
    "locations": ["Phnom Penh"],
    "salary": "$350 - $450 Negotiable",
    "schedule": "Full-time",
    "categories": ["Sales / Marketing", "Business Administration"],
}

DETAIL_URL = "https://bongthom.com/job_detail/view_detail_42739.html"

#: A rendered page with a Khmer-default block (job 42739's real shape) whose
#: first rows are Khmer label text and whose English rows follow.
DETAIL_HTML = """
<html><body>
<ul>
  <li class="clearfix en"><strong><span class="fas fa-rainbow"></span>បរិយាកាស:</strong>
      <span class="value">ក្រៅ</span></li>
  <li class="clearfix en"><strong><span class="fas fa-language"></span>ភាសា:</strong>
      <span class="value">អង់គ្លេស, ខ្មែរ</span></li>
  <li class="clearfix en"><strong><span class="fa fa-map-marker"></span>ទីតាំង:</strong>
      <span class="value">រាជធានីភ្នំពេញ</span></li>
  <li class="clearfix en"><strong>Environment:</strong>
      <span class="value">Outdoors</span></li>
  <li class="clearfix en"><strong>Languages:</strong>
      <span class="value">English, Khmer</span></li>
  <li class="clearfix en"><strong>Location:</strong>
      <span class="value">Phnom Penh</span></li>
  <li class="clearfix en"><strong>Career Category:</strong>
      <span class="value">Sales / Marketing, Business Administration</span></li>
  <li class="clearfix en"><strong>Schedule:</strong>
      <span class="value">Full-time</span></li>
  <li class="clearfix en"><strong>Salary:</strong>
      <span class="value">$350 - $450 Negotiable</span></li>
</ul>
</body></html>
"""

PAGE_ONE = {
    "current_page": 1,
    "data": [LISTING],
    "last_page": 1,
    "per_page": 40,
    "total": 1,
}


class _Resp:
    """Minimal stand-in for ``requests.Response`` (json + text)."""

    def __init__(self, *, payload: object = None, text: str = "") -> None:
        self._payload = payload
        self.text = text

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class TestModels:
    def test_from_payload_merges_listing_embed_and_workplace(self) -> None:
        job = RawBongthomJob.from_payload(LISTING, EMBED, WORKPLACE, original_url=DETAIL_URL)
        assert job.source_job_id == "42739"
        assert job.job_title == "Sales Manager"
        assert job.company_name == "H O S Trading Co.Ltd."
        assert job.company_logo_url is None  # error_pic placeholder dropped
        assert job.description_htmls == ["<p>We are now looking for a qualified candidate.</p>"]
        assert job.duty_texts == ["Visit assigned outlets daily.", "Prepare weekly reports."]
        assert job.benefit_texts == ["International mentoring and professional development."]
        assert job.qualification_texts == ["Business Administration"]
        assert job.experience_texts == [
            "sales management experience",
            "team leadership experience",
        ]
        assert job.skills_raw == ["Negotiation", "English", "Negotiation"]
        assert job.experience_years_raw == [3, 5]
        assert job.categories_raw == ["Sales / Marketing", "Business Administration"]
        assert job.location_text == "Phnom Penh"
        assert job.salary_text_raw == "$350 - $450 Negotiable"
        assert job.employment_type_raw == "Full-time"
        assert job.posting_date is not None and job.posting_date.year == 2026
        assert job.closing_date is not None and job.closing_date.month == 12

    def test_from_payload_listing_only_falls_back(self) -> None:
        job = RawBongthomJob.from_payload(LISTING, None, None, original_url=DETAIL_URL)
        assert job.source_job_id == "42739"
        assert job.job_title == "Sales Manager"
        assert job.company_name == "H O S Trading Co.Ltd."
        assert job.description_htmls == []
        assert job.skills_raw == []
        assert job.location_text is None
        assert job.salary_text_raw is None
        assert job.employment_type_raw is None
        assert job.posting_date is not None

    def test_real_logo_is_kept(self) -> None:
        embed = {**EMBED, "logo": "https://cdn.example.com/logo.png"}
        job = RawBongthomJob.from_payload(LISTING, embed, WORKPLACE, original_url=DETAIL_URL)
        assert job.company_logo_url == "https://cdn.example.com/logo.png"

    def test_rejects_non_object_listing(self) -> None:
        with pytest.raises(ValueError):
            RawBongthomJob.from_payload([], EMBED, WORKPLACE, original_url=DETAIL_URL)

    def test_missing_id_is_rejected(self) -> None:
        listing = {**LISTING, "id": None}
        embed = {**EMBED, "id": None}
        with pytest.raises(ValueError):
            RawBongthomJob.from_payload(listing, embed, WORKPLACE, original_url=DETAIL_URL)

    def test_missing_title_is_rejected(self) -> None:
        listing = {**LISTING, "title": ""}
        embed = {**EMBED, "title": ""}
        with pytest.raises(ValidationError):
            RawBongthomJob.from_payload(listing, embed, WORKPLACE, original_url=DETAIL_URL)


class TestClient:
    def test_parse_workplace_keeps_english_rows_and_ignores_khmer(self) -> None:
        workplace = BongthomClient.parse_workplace(DETAIL_HTML)
        assert workplace["locations"] == ["Phnom Penh"]
        assert workplace["salary"] == "$350 - $450 Negotiable"
        assert workplace["schedule"] == "Full-time"
        assert workplace["categories"] == ["Sales / Marketing", "Business Administration"]
        assert workplace["environment"] == "Outdoors"
        assert workplace["languages"] == "English, Khmer"

    def test_parse_workplace_empty_page(self) -> None:
        workplace = BongthomClient.parse_workplace("<html><body>nothing here</body></html>")
        assert workplace["locations"] == []
        assert workplace["salary"] is None
        assert workplace["schedule"] is None

    def test_fetch_hydrates_each_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = BongthomSettings()

        def fake_get(url: str, *, params: object = None, what: str = "") -> _Resp:
            if url == settings.list_url:
                return _Resp(payload=PAGE_ONE)
            if "get_embed" in url:
                return _Resp(payload=EMBED)
            return _Resp(text=DETAIL_HTML)

        client = BongthomClient(settings=settings)
        monkeypatch.setattr(client, "_get", fake_get)
        jobs = client.fetch_raw_jobs()
        assert len(jobs) == 1
        assert jobs[0]["id"] == "42739"
        assert jobs[0]["embed"]["id"] == 42739
        assert jobs[0]["workplace"]["locations"] == ["Phnom Penh"]
        assert jobs[0]["url"] == DETAIL_URL

    def test_fetch_raises_on_zero_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        empty = {**PAGE_ONE, "data": []}
        client = BongthomClient(settings=BongthomSettings())
        monkeypatch.setattr(
            client,
            "_get",
            lambda url, *, params=None, what="": SimpleNamespace(json=lambda: empty, text=""),
        )
        with pytest.raises(BongthomResponseError):
            client.fetch_raw_jobs()

    def test_fetch_degrades_when_detail_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = BongthomSettings()

        def fake_get(url: str, *, params: object = None, what: str = "") -> _Resp:
            if url == settings.list_url:
                return _Resp(payload=PAGE_ONE)
            if "get_embed" in url:
                return _Resp(payload=None)  # non-JSON -> embed None
            raise AssertionError("workplace fetch should be caught by _fetch_workplace")

        client = BongthomClient(settings=settings)
        monkeypatch.setattr(client, "_get", fake_get)
        monkeypatch.setattr(client, "_fetch_workplace", lambda job_id: {})
        jobs = client.fetch_raw_jobs()
        assert len(jobs) == 1
        assert jobs[0]["embed"] is None
        assert jobs[0]["workplace"] == {}


class TestParser:
    def test_parses_valid_and_skips_malformed(self) -> None:
        parser = BongthomParser()
        raw = [
            {
                "id": "42739",
                "listing": LISTING,
                "embed": EMBED,
                "workplace": WORKPLACE,
                "url": DETAIL_URL,
            },
            {"id": "", "listing": None, "embed": None, "workplace": None, "url": DETAIL_URL},
            {
                "id": "x",
                "listing": {**LISTING, "id": None},
                "embed": None,
                "workplace": None,
                "url": DETAIL_URL,
            },
        ]
        jobs = parser.parse_jobs(raw)
        assert len(jobs) == 1
        assert jobs[0].source_job_id == "42739"


class TestCleaner:
    def test_disclosed_salary_and_mappings(self) -> None:
        job = RawBongthomJob.from_payload(LISTING, EMBED, WORKPLACE, original_url=DETAIL_URL)
        cleaned = BongthomCleaner().clean_job(job)
        assert cleaned.salary_min == 350.0
        assert cleaned.salary_max == 450.0
        assert cleaned.salary_disclosed is True
        assert cleaned.currency_iso_code == "USD"
        assert cleaned.pay_period == "monthly"
        assert cleaned.employment_type_code == "full_time"
        assert cleaned.remote_work_type_code is None
        assert cleaned.experience_years_min == 3
        assert cleaned.experience_years_max is None
        assert cleaned.location_cleaned == "Phnom Penh"
        assert cleaned.skills == ["negotiation", "english"]
        assert cleaned.apply_url == DETAIL_URL
        assert "qualified candidate" in (cleaned.description_clean or "")
        assert "Visit assigned outlets daily." in (cleaned.description_clean or "")
        assert "International mentoring" in (cleaned.description_clean or "")
        assert "Business Administration" in (cleaned.description_clean or "")
        assert "sales management experience" in (cleaned.description_clean or "")

    def test_single_value_salary_is_lower_bound(self) -> None:
        workplace = {**WORKPLACE, "salary": "$4000"}
        job = RawBongthomJob.from_payload(LISTING, EMBED, workplace, original_url=DETAIL_URL)
        cleaned = BongthomCleaner().clean_job(job)
        assert cleaned.salary_min == 4000.0
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is True

    def test_negotiable_salary_is_undisclosed(self) -> None:
        workplace = {**WORKPLACE, "salary": "Negotiable"}
        job = RawBongthomJob.from_payload(LISTING, EMBED, workplace, original_url=DETAIL_URL)
        cleaned = BongthomCleaner().clean_job(job)
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_reversed_salary_is_swapped(self) -> None:
        workplace = {**WORKPLACE, "salary": "$900 - $300"}
        job = RawBongthomJob.from_payload(LISTING, EMBED, workplace, original_url=DETAIL_URL)
        cleaned = BongthomCleaner().clean_job(job)
        assert cleaned.salary_min == 300.0
        assert cleaned.salary_max == 900.0

    def test_parse_salary_variants(self) -> None:
        assert parse_salary("$1000 - $1500") == (1000.0, 1500.0)
        assert parse_salary("$350 - $450 Negotiable") == (350.0, 450.0)
        assert parse_salary("$250 Other Benefits") == (250.0, None)
        assert parse_salary("Negotiable + Based on Experience") == (None, None)
        assert parse_salary("N/A") == (None, None)
        assert parse_salary(None) == (None, None)

    def test_short_term_maps_to_temporary(self) -> None:
        workplace = {**WORKPLACE, "schedule": "Short-term"}
        job = RawBongthomJob.from_payload(LISTING, EMBED, workplace, original_url=DETAIL_URL)
        cleaned = BongthomCleaner().clean_job(job)
        assert cleaned.employment_type_code == "temporary"

    def test_combined_schedule_is_left_unmapped(self) -> None:
        # A combined label names two engagement types at once, so no single
        # ref code is right; the raw value survives in raw_payload.
        workplace = {**WORKPLACE, "schedule": "Full-time, Part-time"}
        job = RawBongthomJob.from_payload(LISTING, EMBED, workplace, original_url=DETAIL_URL)
        cleaned = BongthomCleaner().clean_job(job)
        assert cleaned.employment_type_code is None
        assert cleaned.raw_payload["workplace"]["schedule"] == "Full-time, Part-time"

    def test_working_from_home_maps_to_remote_country(self) -> None:
        workplace = {**WORKPLACE, "locations": ["Working from home / online, Siemreap Province"]}
        job = RawBongthomJob.from_payload(LISTING, EMBED, workplace, original_url=DETAIL_URL)
        cleaned = BongthomCleaner().clean_job(job)
        assert cleaned.remote_work_type_code == "remote_country"

    def test_clean_jobs_batch(self) -> None:
        job = RawBongthomJob.from_payload(LISTING, EMBED, WORKPLACE, original_url=DETAIL_URL)
        cleaned = BongthomCleaner().clean_jobs([job, job])
        assert len(cleaned) == 2


class TestValidator:
    def _jobs(self, n: int) -> list[RawBongthomJob]:
        return [
            RawBongthomJob.from_payload(
                {**LISTING, "id": 42710000 + i},
                {**EMBED, "id": 42710000 + i},
                WORKPLACE,
                original_url=f"https://bongthom.com/job_detail/view_detail_{42710000 + i}.html",
            )
            for i in range(n)
        ]

    def test_healthy_batch_passes(self) -> None:
        jobs = self._jobs(15)
        report = BongthomBatchValidator().validate(list(jobs), jobs)
        assert report.passed is True
        assert report.total_parsed == 15

    def test_too_few_jobs_fails(self) -> None:
        jobs = self._jobs(3)
        report = BongthomBatchValidator().validate(list(jobs), jobs)
        assert report.passed is False
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_zero_raw_records_fails(self) -> None:
        report = BongthomBatchValidator().validate([], [])
        assert report.passed is False

    def test_duplicate_ids_are_flagged(self) -> None:
        jobs = self._jobs(15)
        report = BongthomBatchValidator().validate(list(jobs), jobs + [jobs[0]])
        assert report.passed is False
        assert report.duplicate_source_job_ids == ["42710000"]

    def test_default_thresholds(self) -> None:
        settings = BongthomValidationSettings()
        assert settings.min_expected_jobs == 10
        assert settings.max_skip_rate == 0.10


class TestSettings:
    def test_defaults(self) -> None:
        settings = BongthomSettings()
        assert settings.list_url == "https://bongthom.com/Job_Controller/get_all"
        assert settings.embed_url == "https://bongthom.com/Job_Controller/get_embed/"
        assert settings.detail_page_base == "https://bongthom.com/job_detail/view_detail_"
        assert settings.max_jobs_per_run == 300
        assert settings.user_agent.startswith("Mozilla/5.0")
        assert settings.detail_url("42") == ("https://bongthom.com/job_detail/view_detail_42.html")
        assert settings.embed_detail_url("42") == (
            "https://bongthom.com/Job_Controller/get_embed/42"
        )
