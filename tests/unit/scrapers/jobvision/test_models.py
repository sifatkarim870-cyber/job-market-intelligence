"""Unit tests for job_market_intel.scrapers.jobvision.models.

Pins how the API's ``data`` dict maps onto ``RawJobvisionJob`` — the
facts confirmed live during recon (r7–r9, 2026-10-07): identity comes
from ``id``+``title``, salary stays in **source units** (millions of
Toman — the cleaner owns scaling), dates come from
``activationTime``/``expireTime`` with a ``firstActivationTime``
fallback, and the five tag sources are read defensively.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.jobvision.models import RawJobvisionJob

PAYLOAD = {
    "id": 1550047,
    "title": "کارمند اداری - خانم",
    "description": '<div dir="rtl"><ul><li>تایپ و تنظیم اسناد</li></ul></div>',
    "activationTime": {"date": "2026-10-03T15:06:50Z"},
    "firstActivationTime": {"date": "2026-09-01T09:00:00Z"},
    "expireTime": {"date": "2026-12-02T15:06:50Z"},
    "workType": {"titleEn": "Full Time"},
    "isInternship": False,
    "isExpired": False,
    "isRemote": False,
    "salary": {"min": 26, "max": 30, "titleFa": "26 - 30 میلیون تومان"},
    "company": {
        "name": {"titleFa": "مجموعه چاپ سجادی", "titleEn": "Sajadi"},
        "logoUrl": "https://fileapi.jobvision.ir/api/v1.0/files/getimage?fileid=1",
        "industries": [{"titleFa": "تولیدی / صنعتی"}],
    },
    "location": {
        "city": {"titleFa": "گرمدره"},
        "province": {"titleFa": "البرز"},
        "country": {"titleFa": "ایران", "titleEn": "Iran"},
    },
    "jobCategories": [{"titleFa": "مسئول دفتر / تایپیست"}],
    "softwareRequirements": [
        {"software": {"titleFa": "Microsoft Word"}, "skill": {"titleFa": "متوسط"}},
        {"software": {"titleFa": "سپیدار"}, "skill": None},
    ],
    "languageRequirements": [
        {"language": {"titleFa": "انگلیسی"}, "skill": {"titleFa": "متوسط"}},
    ],
    "skills": [],
    "linkOutAddress": None,
}
URL = "https://jobvision.ir/jobs/1550047/استخدام-کارمند-اداری---خانم"


def _from(payload=PAYLOAD, *, url=URL) -> RawJobvisionJob:
    return RawJobvisionJob.from_payload(payload, original_url=url)


class TestIdentity:
    def test_core_fields(self) -> None:
        job = _from()
        assert job.source_job_id == "1550047"  # int → str
        assert job.job_title == "کارمند اداری - خانم"
        assert job.original_url == URL

    def test_empty_title_raises(self) -> None:
        with pytest.raises(ValidationError):
            _from({**PAYLOAD, "title": "   "})

    def test_missing_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            _from({**PAYLOAD, "id": None})

    def test_empty_url_raises(self) -> None:
        with pytest.raises(ValidationError):
            _from(PAYLOAD, url="")

    def test_non_dict_payload_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            RawJobvisionJob.from_payload(None, original_url=URL)
        with pytest.raises(ValueError):
            RawJobvisionJob.from_payload([PAYLOAD], original_url=URL)

    def test_raw_payload_is_the_full_dict(self) -> None:
        job = _from()
        # Pydantic copies dict fields on validation — equality, not identity.
        assert job.raw_payload == PAYLOAD
        assert job.raw_payload["isRemote"] is False  # unmodeled keys kept


class TestCompany:
    def test_persian_name_logo_and_industries(self) -> None:
        job = _from()
        assert job.company_name == "مجموعه چاپ سجادی"
        assert job.company_logo_url is not None
        assert job.industry_raws == ["تولیدی / صنعتی"]

    def test_english_name_fallback(self) -> None:
        payload = {**PAYLOAD, "company": {"name": {"titleEn": "Sajadi Co"}}}
        assert _from(payload).company_name == "Sajadi Co"

    def test_missing_company_is_anonymous_not_a_crash(self) -> None:
        payload = {**PAYLOAD, "company": None}
        job = _from(payload)
        assert job.company_name == "Anonymous"
        assert job.company_logo_url is None
        assert job.industry_raws == []


class TestSalary:
    def test_bounds_kept_in_source_units_of_millions(self) -> None:
        # The raw model must NOT scale — normalization belongs to the
        # cleaner (titleEn: "26 - 30 Million Tomans" beside min=26).
        job = _from()
        assert job.salary_min_raw == 26
        assert job.salary_max_raw == 30
        assert job.salary_title_fa == "26 - 30 میلیون تومان"

    def test_null_salary_is_undisclosed_shape(self) -> None:
        job = _from({**PAYLOAD, "salary": None})
        assert job.salary_min_raw is None
        assert job.salary_max_raw is None
        assert job.salary_title_fa is None

    def test_zero_bound_is_kept_for_the_cleaner_to_rule_on(self) -> None:
        job = _from({**PAYLOAD, "salary": {"min": 0, "max": 30}})
        assert job.salary_min_raw == 0  # not None — ≤0 is the cleaner's call
        assert job.salary_max_raw == 30

    def test_string_and_float_bounds_coerce(self) -> None:
        job = _from({**PAYLOAD, "salary": {"min": "26", "max": 26.0}})
        assert job.salary_min_raw == 26
        assert job.salary_max_raw == 26

    def test_garbage_bound_is_none(self) -> None:
        job = _from({**PAYLOAD, "salary": {"min": "n/a", "max": 30}})
        assert job.salary_min_raw is None


class TestDates:
    def test_activation_is_posting_expire_is_closing(self) -> None:
        job = _from()
        assert job.posting_date == datetime(2026, 10, 3, 15, 6, 50, tzinfo=UTC)
        assert job.closing_date == datetime(2026, 12, 2, 15, 6, 50, tzinfo=UTC)

    def test_first_activation_fallback_when_activation_missing(self) -> None:
        payload = {**PAYLOAD}
        payload.pop("activationTime")
        job = _from(payload)
        assert job.posting_date == datetime(2026, 9, 1, 9, 0, tzinfo=UTC)

    def test_garbage_date_is_none_not_a_crash(self) -> None:
        job = _from({**PAYLOAD, "expireTime": {"date": "not-a-date"}})
        assert job.closing_date is None
        assert job.posting_date is not None  # unaffected

    def test_missing_expire_is_none(self) -> None:
        payload = {**PAYLOAD}
        payload.pop("expireTime")
        assert _from(payload).closing_date is None


class TestEmploymentAndLocation:
    def test_work_type_kept_raw(self) -> None:
        assert _from().work_type_en == "Full Time"

    def test_internship_flag_survives(self) -> None:
        assert _from({**PAYLOAD, "isInternship": True}).is_internship is True

    def test_location_parts_city_then_province(self) -> None:
        assert _from().location_parts == ["گرمدره", "البرز"]

    def test_city_missing_falls_back_to_province_only(self) -> None:
        payload = {**PAYLOAD, "location": {**PAYLOAD["location"], "city": None}}
        assert _from(payload).location_parts == ["البرز"]

    def test_no_location_is_empty_list(self) -> None:
        assert _from({**PAYLOAD, "location": None}).location_parts == []

    def test_country_is_kept_for_currency_evidence_only(self) -> None:
        job = _from()
        assert job.country_fa == "ایران"


class TestTagSources:
    def test_all_five_sources_read(self) -> None:
        job = _from()
        assert job.category_raws == ["مسئول دفتر / تایپیست"]
        # softwareRequirements nests under ``software``; the paired
        # skill level (متوسط) is deliberately not a tag.
        assert job.software_names == ["Microsoft Word", "سپیدار"]
        # languageRequirements nests under ``language``.
        assert job.language_names == ["انگلیسی"]
        assert job.industry_raws == ["تولیدی / صنعتی"]
        assert job.skills_raws == []  # empty on 55/55 sampled jobs

    def test_malformed_lists_are_empty_not_a_crash(self) -> None:
        job = _from(
            {
                **PAYLOAD,
                "jobCategories": "not-a-list",
                "softwareRequirements": [None, {"skill": {"titleFa": "x"}}],
            }
        )
        assert job.category_raws == []
        assert job.software_names == []  # no ``software`` key → nothing


class TestMisc:
    def test_link_out_address_none(self) -> None:
        assert _from().link_out_address is None

    def test_link_out_address_present(self) -> None:
        payload = {**PAYLOAD, "linkOutAddress": "https://apply.example.com/x"}
        assert _from(payload).link_out_address == "https://apply.example.com/x"

    def test_description_html_kept_verbatim(self) -> None:
        assert _from().description_html == PAYLOAD["description"]
