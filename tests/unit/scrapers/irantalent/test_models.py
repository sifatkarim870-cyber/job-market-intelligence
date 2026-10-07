"""Unit tests for job_market_intel.scrapers.irantalent.models.

Pins how the search row maps onto ``RawIrantalentJob`` — the facts
confirmed live during recon (probes r6-r10, 2026-10-07): identity from
``id``+``slug``, source-language title selection via ``language``
(EN job keeps ``title``, otherwise Persian-first), salary stays in
**source units** (whole Toman — no scaling anywhere), dates come from
``lived_at`` with a ``created_at`` fallback, the display company name
is ``employer.name`` (not the legal ``employer.title``), and the two
tag sources are read English-first.

Values are verbatim from live rows 184579 (regular) and 184576
(anonymous); only the multi-KB prose fields are shortened.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.irantalent.models import RawIrantalentJob

PAYLOAD = {
    "id": 184579,
    "slug": "customer-success-specialist",
    "language": "en",
    "title": "Customer Success Specialist",
    "title_farsi": "کارشناس تجربه و موفقیت مشتری",
    "reference_code": "P0184-579",
    "created_at": "2026-10-06",
    "lived_at": "2026-10-06 18:05:33",
    "expired_at": None,
    "role_description": "Role Overview:<br><br>We’re looking for…",
    "role_description_farsi": None,
    "location_text": "Tehran",
    "location_text_farsi": "تهران",
    "location": {"id": 216, "title": "Tehran", "title_farsi": "تهران", "parent": {"id": 2}},
    "work_type": "on_site",
    "salary_from": None,
    "salary_to": None,
    "is_show_salary": False,
    "employment_type": {
        "id": 186,
        "title": "Full Time",
        "title_farsi": "تمام وقت",
        "slug": "Full-Time-employment-type",
    },
    "seniority": [
        {
            "id": 273,
            "title": "Experienced professional",
            "title_farsi": "کارشناس ارشد / متخصص",
            "slug": "experienced-professional",
        }
    ],
    "job_category": [
        {
            "id": 589,
            "title": "Customer Success & Support Operations",
            "title_farsi": "موفقیت مشتریان و عملیات پشتیبانی",
            "slug": "customer_success",
        }
    ],
    "status": {"title": "Live", "id": 169},
    "is_anonymous": False,
    "redirection_url": None,
    "brand_data": {
        "uuid": "c819661f-0426-4592-8580-940406fa056d",
        "logo_url": "https://minio1.sc.irtalent.cloud/brand-data/brand_data_2972Es2_63578d735ef59.png",
        "slug": "eways",
        "name_en": "Eways",
        "name_fa": "ایویز",
        "industry": {
            "id": 257,
            "title": "IT, Software and Internet Services",
            "title_farsi": "فناوری اطلاعات، خدمات اینترنتی و نرم افزار",
            "slug": "IT-software-internet-services",
        },
        "company_size": {
            "id": 29,
            "title": "100-499 employees",
            "title_farsi": "100-499کارمند",
            "slug": "100-499-employees",
        },
    },
    "anonymous_data": None,
    "employer": {
        "id": 1268,
        "title": "Iranian Omid Internet Bazaar",  # LEGAL name
        "slug": "iranian-internet-bazar",
        "name": "Eways",  # display name
        "name_farsi": "ایویز",
        "industry_id": "257",
        "title_farsi": "بازار اینترنتی ایرانیان امید",
        "logo_path": "https://minio1.sc.irtalent.cloud/employer-logo/F271-1275_logo.jpg",
    },
}

ANON_PAYLOAD = {
    "id": 184576,
    "slug": "accountant",
    "language": "fa",
    "title": "Accountant",
    "title_farsi": "حسابدار",
    "created_at": "2026-10-05",
    "lived_at": "2026-10-05 09:15:00",
    "expired_at": None,
    "role_description": '<p dir="rtl">شرح شغل…</p>',
    "location_text": "Isfahan",
    "location_text_farsi": "اصفهان",
    "work_type": "hybrid",
    "salary_from": 350_000_000,
    "salary_to": 450_000_000,
    "is_show_salary": True,
    "employment_type": {"id": 187, "title": "Part Time", "title_farsi": "نیمه وقت"},
    "job_category": [
        {"id": 601, "title": "Accounting", "title_farsi": "حسابداری", "slug": "accounting"}
    ],
    "is_anonymous": True,
    "brand_data": None,
    "anonymous_data": {
        "slug": "a-leading-company-active-in-electrical-industry",
        "name_en": "A leading Company Active in Electrical Industry",
        "name_fa": "یک شرکت پیشرو فعال در صنعت برق",
        "industry": {
            "id": 231,
            "title": "Electrical Equipment",
            "title_farsi": "تجهیزات برقی",
            "slug": "electrical-equipment",
        },
    },
    "employer": {
        "id": 18512,
        "name": "A leading Company Active in Electrical Industry",
        "name_farsi": "یک شرکت پیشرو فعال در صنعت برق",
        "title": "A leading Company Active in Electrical Industry",
        "slug": "a-leading-company-active-in-electrical-industry",
    },
}

URL = "https://www.irantalent.com/en/job/customer-success-specialist/184579"
ANON_URL = "https://www.irantalent.com/fa/job/accountant/184576"


def _from(payload=PAYLOAD, *, url=URL) -> RawIrantalentJob:
    return RawIrantalentJob.from_payload(payload, original_url=url)


class TestIdentity:
    def test_core_fields(self) -> None:
        job = _from()
        assert job.source_job_id == "184579"  # int → str
        assert job.job_title == "Customer Success Specialist"  # language="en"
        assert job.language == "en"
        assert job.original_url == URL

    def test_persian_job_keeps_the_persian_title(self) -> None:
        job = _from(ANON_PAYLOAD, url=ANON_URL)
        assert job.job_title == "حسابدار"  # language="fa" → title_farsi first
        assert job.language == "fa"

    def test_missing_language_prefers_persian(self) -> None:
        # Rows without a language label still carry both titles;
        # Persian-first is the source's dominant locale (fa+multi = 164/180).
        job = _from({**PAYLOAD, "language": None})
        assert job.job_title == "کارشناس تجربه و موفقیت مشتری"

    def test_empty_title_raises(self) -> None:
        with pytest.raises(ValidationError):
            _from({**PAYLOAD, "title": "   ", "title_farsi": None})

    def test_missing_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            _from({**PAYLOAD, "id": None})

    def test_empty_url_raises(self) -> None:
        with pytest.raises(ValidationError):
            _from(PAYLOAD, url="   ")


class TestCompany:
    def test_display_name_wins_over_legal_title(self) -> None:
        job = _from()
        # employer.name = display ("Eways"), employer.title = legal
        # ("Iranian Omid Internet Bazaar") — Persian-first display.
        assert job.company_name == "ایویز"

    def test_anonymous_row_resolves_from_employer(self) -> None:
        job = _from(ANON_PAYLOAD, url=ANON_URL)
        assert job.company_name == "یک شرکت پیشرو فعال در صنعت برق"

    def test_missing_employer_falls_back_to_anonymous(self) -> None:
        job = _from({**PAYLOAD, "employer": None})
        assert job.company_name == "Anonymous"

    def test_brand_logo_precedes_employer_logo(self) -> None:
        job = _from()
        assert job.company_logo_url.endswith("brand_data_2972Es2_63578d735ef59.png")

    def test_employer_logo_used_when_brand_absent(self) -> None:
        job = _from({**PAYLOAD, "brand_data": None})
        assert job.company_logo_url.endswith("F271-1275_logo.jpg")


class TestDatesAndSalary:
    def test_lived_at_is_posting_date(self) -> None:
        job = _from()
        assert job.posting_date == datetime(2026, 10, 6, 18, 5, 33, tzinfo=UTC)

    def test_created_at_date_only_fallback(self) -> None:
        job = _from({**PAYLOAD, "lived_at": None})
        assert job.posting_date == datetime(2026, 10, 6, tzinfo=UTC)

    def test_unparseable_dates_are_none_not_a_crash(self) -> None:
        job = _from({**PAYLOAD, "lived_at": "??", "created_at": "??", "expired_at": "??"})
        assert job.posting_date is None
        assert job.closing_date is None

    def test_expired_at_is_closing_date(self) -> None:
        job = _from({**PAYLOAD, "expired_at": "2026-12-01 00:00:00"})
        assert job.closing_date == datetime(2026, 12, 1, tzinfo=UTC)

    def test_salary_stays_in_whole_toman_source_units(self) -> None:
        job = _from(ANON_PAYLOAD, url=ANON_URL)
        # No scaling in the model — 350,000,000 Toman, exactly as sent.
        assert job.salary_min_raw == 350_000_000
        assert job.salary_max_raw == 450_000_000
        assert job.salary_show_flag is True

    def test_null_bounds_and_false_flag(self) -> None:
        job = _from()
        assert job.salary_min_raw is None
        assert job.salary_max_raw is None
        assert job.salary_show_flag is False


class TestTagsAndLocation:
    def test_category_is_english_first(self) -> None:
        job = _from()
        assert job.category_raws == ["Customer Success & Support Operations"]

    def test_industry_comes_from_brand_block(self) -> None:
        job = _from()
        assert job.industry_raws == ["IT, Software and Internet Services"]

    def test_industry_from_anonymous_block(self) -> None:
        job = _from(ANON_PAYLOAD, url=ANON_URL)
        assert job.industry_raws == ["Electrical Equipment"]

    def test_missing_nullable_blocks_yield_no_industry(self) -> None:
        job = _from({**PAYLOAD, "brand_data": None})
        assert job.industry_raws == []

    def test_location_prefers_persian(self) -> None:
        job = _from()
        assert job.location_text == "تهران"

    def test_work_type_title_captured_for_employment_mapping(self) -> None:
        job = _from()
        assert job.work_type_en == "Full Time"

    def test_raw_payload_is_kept_verbatim(self) -> None:
        # Pydantic re-validates the dict, so assert content equality
        # (the payload must survive unmodified — same convention as the
        # Jobvision model test).
        assert _from().raw_payload == PAYLOAD


def test_non_dict_payload_raises() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        RawIrantalentJob.from_payload(["not", "a", "dict"], original_url=URL)
