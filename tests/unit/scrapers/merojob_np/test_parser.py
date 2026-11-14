"""Unit tests for Merojob (Nepal) parser."""

from __future__ import annotations

from job_market_intel.scrapers.merojob_np.parser import MerojobParser


def test_merojob_parser_complete():
    parser = MerojobParser()
    listing = {
        "id": 204772,
        "title": "Sales and Marketing Executive",
        "slug": "sales-and-marketing-executive-257",
        "absolute_url": "/sales-and-marketing-executive-257/",
        "client": {
            "client_name": "Capital Soft",
            "org_name": "Capital Soft",
            "client_image": "/media/uploads/profile-pics/ad5a96d9.jpg",
        },
        "skills": ["Negotiation", "Presentation", "Technical Sales"],
        "job_locations": [
            {"address": "Tokha, Kathmandu"}
        ],
        "offered_salary": {
            "currency": "NRs",
            "minimum": 30000.0,
            "maximum": 60000.0,
            "unit": "Monthly",
        },
        "available_for": ["Full Time"],
        "posted_at": "2026-11-13T11:51:43.468122Z",
        "deadline": "2026-11-28T18:10:00Z",
    }
    detail = {
        "description": "<p>Responsible for sales proposals and client visits.</p>",
        "specification": "<ul><li>Bachelor degree required.</li></ul>",
    }

    job = parser.parse_job(listing, detail)
    assert job is not None
    assert job.source_job_id == "204772"
    assert job.job_title == "Sales and Marketing Executive"
    assert job.company_name == "Capital Soft"
    assert job.company_logo_url == "https://api.merojob.com/media/uploads/profile-pics/ad5a96d9.jpg"
    assert "Negotiation" in job.skills
    assert "Kathmandu" in job.location_cleaned
    assert "Nepal" in job.location_cleaned
    assert job.salary_min == 30000.0
    assert job.salary_max == 60000.0
    assert job.salary_disclosed is True
    assert job.currency_iso_code == "NPR"
    assert job.pay_period == "monthly"
    assert job.employment_type_code == "full_time"
    assert "Responsible for sales proposals" in job.description_clean
    assert "Bachelor degree required" in job.description_clean
    assert job.original_url == "https://merojob.com/sales-and-marketing-executive-257/"
    assert job.posting_date is not None
    assert job.closing_date is not None


def test_merojob_parser_minimal():
    parser = MerojobParser()
    listing = {
        "id": 12345,
        "title": "Minimal Vacancy",
        "slug": "minimal-vacancy",
    }
    job = parser.parse_job(listing, None)
    assert job is not None
    assert job.source_job_id == "12345"
    assert job.job_title == "Minimal Vacancy"
    assert job.company_name == "Confidential / Undisclosed"
    assert job.salary_disclosed is False
    assert job.location_cleaned == "Nepal"
    assert job.original_url == "https://merojob.com/minimal-vacancy/"
