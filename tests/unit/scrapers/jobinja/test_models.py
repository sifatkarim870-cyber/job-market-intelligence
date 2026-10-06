"""Unit tests for job_market_intel.scrapers.jobinja.models.

Pins ``from_page_html``'s contract against the page shapes confirmed
live (2026-10-07): JSON-LD ``JobPosting`` as the primary record (6/6
sampled) plus the ``<h4>…</h4><div class="tags">`` sections for
location/skills/category/salary text — including the section-matching
decisions the cleaner depends on (prefix-matched headings, the
negotiate mark, Persian-numeral salary text kept raw here).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.jobinja.models import RawJobinjaJob

_CANONICAL_URL = (
    "https://jobinja.ir/companies/maron-system/jobs/tuti/"
    "%D8%A7%D8%B3%D8%AA%D8%AE%D8%AF%D8%A7%D9%85-%DA%A9%D8%A7%D8%B1%D8%B4"
    "%D9%86%D8%A7%D8%B3-%D9%81%D8%B1%D9%88%D8%B4-%D8%A8%DB%8C%D9%86-"
    "%D8%A7%D9%84%D9%85%D9%84%D9%84%DB%8C"
)


def _job_posting(**overrides) -> dict:
    """The observed JobPosting shape (job 1118910, Maron System, IR)."""
    record = {
        "@type": "JobPosting",
        "@context": "https://schema.org",
        "identifier": {"@type": "PropertyValue", "value": "1118910"},
        "title": "کارشناس فروش بین المللی",
        "description": '<div dir="rtl">ما به دنبال فردی هستیم.</div>',
        "datePosted": "2026-10-06",
        "employmentType": "FULL_TIME",
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "IRT",
            "value": 45000000,
            "unitText": "MONTH",
        },
        "hiringOrganization": {
            "name": "توسعه نرم افزار مارون | Maron System",
            "logo": "https://thumb2.jobinjacdn.com/x/main.png",
        },
        "jobLocation": {"address": {"addressCountry": {"name": "IR"}}},
        "jobLocationType": "TELECOMMUTE",
    }
    record.update(overrides)
    return record


def _page(ld: dict | None = None, *, sections_html: str = "") -> str:
    """A Jobinja-shaped detail page: JSON-LD block + tags sections."""
    payload = ld if ld is not None else _job_posting()
    return (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(payload, ensure_ascii=False)}</script>'
        "</head><body>"
        '<h1>کارشناس فروش بین المللی</h1>'
        f"{sections_html}"
        "</body></html>"
    )


def _standard_sections() -> str:
    """The section block observed on the sampled job page."""
    return (
        '<h4>دسته\u200cبندی شغلی</h4><div class="tags">'
        '<span class="black">فروش و بازاریابی</span></div>'
        '<h4>موقعیت مکانی</h4><div class="tags">'
        '<span class="black">تهران ، تهران</span></div>'
        '<h4>نوع همکاری</h4><div class="tags">'
        '<span class="black">تمام وقت</span></div>'
        '<h4>حقوق</h4><div class="tags">'
        '<span class="black">از ۴۵,۰۰۰,۰۰۰ تومان</span></div>'
        '<h4>مهارت\u200cهای مورد نیاز</h4><div class="tags">'
        "<span>فروش بین المللی</span><span>فروش B2B</span></div>"
    )


class TestCoreFields:
    def test_identity_and_core_fields(self) -> None:
        job = RawJobinjaJob.from_page_html(_page(sections_html=_standard_sections()),
                                           original_url=_CANONICAL_URL)
        assert job.source_job_id == "1118910"
        assert job.job_title == "کارشناس فروش بین المللی"
        assert job.company_name == "توسعه نرم افزار مارون | Maron System"
        assert job.company_logo_url == "https://thumb2.jobinjacdn.com/x/main.png"
        assert job.country_code == "IR"
        assert job.is_telecommute is True
        assert job.original_url == _CANONICAL_URL

    def test_date_only_posting_date_is_utc_midnight(self) -> None:
        job = RawJobinjaJob.from_page_html(_page(), original_url=_CANONICAL_URL)
        assert job.posting_date == datetime(2026, 10, 6, tzinfo=UTC)

    def test_invalid_posting_date_is_none_not_a_crash(self) -> None:
        job = RawJobinjaJob.from_page_html(
            _page(_job_posting(datePosted="not-a-date")), original_url=_CANONICAL_URL
        )
        assert job.posting_date is None

    def test_missing_valid_through_is_none(self) -> None:
        job = RawJobinjaJob.from_page_html(_page(), original_url=_CANONICAL_URL)
        assert job.closing_date is None

    def test_telecommute_absent_means_onsite(self) -> None:
        job = RawJobinjaJob.from_page_html(
            _page(_job_posting(jobLocationType=None)), original_url=_CANONICAL_URL
        )
        assert job.is_telecommute is False

    def test_identifier_as_plain_text_is_accepted(self) -> None:
        job = RawJobinjaJob.from_page_html(
            _page(_job_posting(identifier="1118910")), original_url=_CANONICAL_URL
        )
        assert job.source_job_id == "1118910"

    def test_logo_imageobject_dict_is_unwrapped(self) -> None:
        job = RawJobinjaJob.from_page_html(
            _page(_job_posting(hiringOrganization={
                "name": "Acme",
                "logo": {"@type": "ImageObject", "url": "https://cdn.example/logo.png"},
            })),
            original_url=_CANONICAL_URL,
        )
        assert job.company_logo_url == "https://cdn.example/logo.png"

    def test_country_as_plain_text_is_accepted(self) -> None:
        job = RawJobinjaJob.from_page_html(
            _page(_job_posting(jobLocation={"address": {"addressCountry": "IR"}})),
            original_url=_CANONICAL_URL,
        )
        assert job.country_code == "IR"

    def test_employment_type_list_yields_first_member(self) -> None:
        job = RawJobinjaJob.from_page_html(
            _page(_job_posting(employmentType=["PART_TIME", "FULL_TIME"])),
            original_url=_CANONICAL_URL,
        )
        assert job.employment_type_raw == "PART_TIME"


class TestSalaryShape:
    def test_monetary_amount_fields(self) -> None:
        job = RawJobinjaJob.from_page_html(_page(), original_url=_CANONICAL_URL)
        assert job.base_salary_value == 45000000
        assert job.salary_currency == "IRT"
        assert job.salary_unit == "MONTH"

    def test_quantitative_value_dict_is_unwrapped(self) -> None:
        job = RawJobinjaJob.from_page_html(
            _page(_job_posting(baseSalary={
                "currency": "IRT",
                "value": {"@type": "QuantitativeValue", "value": 40000000},
                "unitText": "MONTH",
            })),
            original_url=_CANONICAL_URL,
        )
        assert job.base_salary_value == 40000000

    @pytest.mark.parametrize("bad", ["", None, "None", "n/a"])
    def test_unparseable_salary_value_is_none(self, bad: object) -> None:
        job = RawJobinjaJob.from_page_html(
            _page(_job_posting(baseSalary={"currency": "IRT", "value": bad})),
            original_url=_CANONICAL_URL,
        )
        assert job.base_salary_value is None

    def test_zero_salary_value_is_kept_raw_for_the_cleaner(self) -> None:
        # ≤0 → "unstated" is a *disclosure* decision; the model only
        # coerces type (mirroring Glints' cleaner-vs-model split).
        job = RawJobinjaJob.from_page_html(
            _page(_job_posting(baseSalary={"currency": "IRT", "value": 0})),
            original_url=_CANONICAL_URL,
        )
        assert job.base_salary_value == 0

    def test_missing_base_salary_entirely_is_none(self) -> None:
        job = RawJobinjaJob.from_page_html(
            _page(_job_posting(baseSalary=None)), original_url=_CANONICAL_URL
        )
        assert job.base_salary_value is None
        assert job.salary_currency is None
        assert job.salary_unit is None


class TestSections:
    def test_standard_sections_map_to_typed_fields(self) -> None:
        job = RawJobinjaJob.from_page_html(
            _page(sections_html=_standard_sections()), original_url=_CANONICAL_URL
        )
        assert job.location_spans == ["تهران ، تهران"]
        assert job.salary_text_spans == ["از ۴۵,۰۰۰,۰۰۰ تومان"]
        assert job.skills_spans == ["فروش بین المللی", "فروش B2B"]
        assert job.category_spans == ["فروش و بازاریابی"]

    def test_negotiate_section_is_captured_verbatim(self) -> None:
        sections = _standard_sections().replace(
            '<span class="black">از ۴۵,۰۰۰,۰۰۰ تومان</span>',
            '<span class="black">توافقی</span>',
        )
        job = RawJobinjaJob.from_page_html(
            _page(sections_html=sections), original_url=_CANONICAL_URL
        )
        assert job.salary_text_spans == ["توافقی"]
        # The JSON-LD number still rides along — the cleaner decides
        # that the visible توافقی withholds it.
        assert job.base_salary_value == 45000000

    def test_missing_sections_are_empty_lists(self) -> None:
        job = RawJobinjaJob.from_page_html(_page(), original_url=_CANONICAL_URL)
        assert job.location_spans == []
        assert job.salary_text_spans == []
        assert job.skills_spans == []
        assert job.category_spans == []

    def test_description_prose_cannot_hijack_section_matching(self) -> None:
        """Regression: the description section is NOT a tags-div.

        Observed live (2026-10-07): a plain ``.*?`` heading group
        backtracked from ``شرح موقعیت شغلی`` across its non-tags body up
        to the next ``</h4>``, producing a mega-heading whose text
        contains "مهارت"/"موقعیت" and stealing the *language* chips as
        "skills". The tempered heading group must keep headings short and
        prefix-matched needles must pick the real ``مهارت‌های مورد نیاز``
        section.
        """
        html = _page(sections_html=(
            '<h4>شرح موقعیت شغلی</h4>'
            '<div class="job-description">ما به دنبال فردی با مهارت های '
            "خوب و تجربه موقعیت کاری قبلی هستیم.</div>"
            '<h4>زبان\u200cهای مورد نیاز</h4><div class="tags">'
            '<span>انگلیسی</span><span>عربی</span></div>'
            '<h4>مهارت\u200cهای مورد نیاز</h4><div class="tags">'
            "<span>فروش B2B</span></div>"
        ))
        job = RawJobinjaJob.from_page_html(html, original_url=_CANONICAL_URL)

        assert job.skills_spans == ["فروش B2B"]
        # No mega-heading swallowed the description text into a key.
        assert all(len(heading) < 60 for heading in job.raw_payload["sections"])

    def test_sections_keep_every_heading_for_audit(self) -> None:
        job = RawJobinjaJob.from_page_html(
            _page(sections_html=_standard_sections()), original_url=_CANONICAL_URL
        )
        headings = job.raw_payload["sections"]
        assert "دسته\u200cبندی شغلی" in headings
        assert "موقعیت مکانی" in headings
        assert headings["حقوق"] == ["از ۴۵,۰۰۰,۰۰۰ تومان"]


class TestShapeDrift:
    def test_page_without_job_posting_raises_value_error(self) -> None:
        # The parser converts this into a skip; the model must fail loudly.
        with pytest.raises(ValueError, match="JobPosting"):
            RawJobinjaJob.from_page_html(
                "<html><script type=\"application/ld+json\">"
                '{"@type": "Organization", "name": "x"}</script></html>',
                original_url=_CANONICAL_URL,
            )

    def test_page_without_ldjson_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="JobPosting"):
            RawJobinjaJob.from_page_html("<html><body>hi</body></html>",
                                          original_url=_CANONICAL_URL)

    def test_broken_ldjson_block_falls_through_to_next(self) -> None:
        html = (
            '<script type="application/ld+json">{not json</script>'
            f'<script type="application/ld+json">{json.dumps(_job_posting())}</script>'
        )
        job = RawJobinjaJob.from_page_html(html, original_url=_CANONICAL_URL)
        assert job.source_job_id == "1118910"


class TestRequiredIdentity:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"identifier": None},
            {"identifier": {"value": ""}},
            {"title": ""},
            {"hiringOrganization": {"name": ""}},
        ],
    )
    def test_missing_identity_field_is_a_validation_error(self, overrides: dict) -> None:
        with pytest.raises(ValidationError):
            RawJobinjaJob.from_page_html(
                _page(_job_posting(**overrides)), original_url=_CANONICAL_URL
            )

    def test_missing_original_url_is_a_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            RawJobinjaJob.from_page_html(_page(), original_url="")

    def test_missing_company_becomes_a_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            RawJobinjaJob.from_page_html(
                _page(_job_posting(hiringOrganization=None)), original_url=_CANONICAL_URL
            )
