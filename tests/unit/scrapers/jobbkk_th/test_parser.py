"""Unit tests for JobBKK (Thailand) parser."""

from __future__ import annotations

from job_market_intel.scrapers.jobbkk_th.models import RawJobbkkJob
from job_market_intel.scrapers.jobbkk_th.parser import JobbkkParser


def test_jobbkk_parser_complete():
    parser = JobbkkParser()
    json_ld = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Kitchen Staff - Ippudo Ramen",
        "description": "Prepare ramen bowls and maintain food safety standards.",
        "occupationalCategory": "Food/Beverage/Cook",
        "datePosted": "2026-11-14T18:05:47+07:00",
        "employmentType": "FULL_TIME",
        "validThrough": "2027-09-24T00:00:00+07:00",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Food Excite Co., Ltd.",
            "logo": "https://store.jobbkk.com/upload/employer/logo.webp",
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "Sukhumvit Rd",
                "addressLocality": "Khlong Toei",
                "addressRegion": "Bangkok",
                "postalCode": "10110",
                "addressCountry": "Thailand",
            },
        },
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "THB",
            "value": {
                "@type": "QuantitativeValue",
                "minValue": 15000,
                "maxValue": 18000,
                "unitText": "MONTH",
            },
        },
    }
    raw = RawJobbkkJob(
        url="https://www.jobbkk.com/jobs/detail/58622/943523",
        emp_id="58622",
        job_id="943523",
        json_ld=json_ld,
        html_title="Kitchen Staff | Food Excite - jobbkk.com",
    )

    job = parser.parse_job(raw)
    assert job is not None
    assert job.source_job_id == "943523"
    assert job.job_title == "Kitchen Staff - Ippudo Ramen"
    assert job.company_name == "Food Excite Co., Ltd."
    assert job.company_logo_url == "https://store.jobbkk.com/upload/employer/logo.webp"
    assert "Bangkok" in job.location_cleaned
    assert "Thailand" in job.location_cleaned
    assert job.salary_min == 15000.0
    assert job.salary_max == 18000.0
    assert job.salary_disclosed is True
    assert job.currency_iso_code == "THB"
    assert job.pay_period == "monthly"
    assert job.employment_type_code == "full_time"
    assert "Prepare ramen bowls" in job.description_clean
    assert job.posting_date is not None
    assert job.closing_date is not None
    assert job.original_url == "https://www.jobbkk.com/jobs/detail/58622/943523"


def test_jobbkk_parser_minimal():
    parser = JobbkkParser()
    json_ld = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "General Technician",
        "description": "General maintenance duties.",
    }
    raw = RawJobbkkJob(
        url="https://www.jobbkk.com/jobs/detail/100/200",
        emp_id="100",
        job_id="200",
        json_ld=json_ld,
    )
    job = parser.parse_job(raw)
    assert job is not None
    assert job.source_job_id == "200"
    assert job.job_title == "General Technician"
    assert job.company_name == "Confidential / Undisclosed"
    assert job.location_cleaned == "Thailand"
    assert job.salary_disclosed is False
    assert job.currency_iso_code == "THB"
