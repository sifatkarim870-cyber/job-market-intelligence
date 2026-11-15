"""Unit tests for GoodWork (Canada) parser."""

from __future__ import annotations

from job_market_intel.scrapers.goodwork_ca.models import RawGoodworkJob
from job_market_intel.scrapers.goodwork_ca.parser import GoodworkParser


def test_goodwork_parser_complete():
    parser = GoodworkParser()
    html_content = """
    <html>
    <body>
    <section id="page" class="ten columns clearfix alpha">
    <p><strong>Position:</strong> Construction Coordinator, on-site, flexible<br />
    <strong>Company:</strong> <a href="https://example.com">Seed the North, Inc.</a><br />
    <strong>Location:</strong> Hazelton, BC / Smithers BC<br /></p>
    <p>Seed the North is an ecological restoration company.</p>
    <p>Remuneration: $60,000 - $75,000 per year</p>
    <p><small>Date posted: Nov 13 2026&nbsp;&nbsp;&nbsp;<strong> ID: </strong> 76937</small></p>
    </section>
    </body>
    </html>
    """
    raw = RawGoodworkJob(
        url="https://www.goodwork.ca/jobs/construction-manager-jobs-76937",
        job_id="76937",
        html_content=html_content,
    )

    job = parser.parse_job(raw)
    assert job is not None
    assert job.source_job_id == "76937"
    assert "Construction Coordinator" in job.job_title
    assert job.company_name == "Seed the North, Inc."
    assert "Hazelton" in job.location_cleaned
    assert "Canada" in job.location_cleaned
    assert job.currency_iso_code == "CAD"
    assert job.salary_min == 60000.0
    assert job.salary_max == 75000.0
    assert job.salary_disclosed is True
    assert job.pay_period == "yearly"
    assert job.employment_type_code == "full_time"
    assert "ecological restoration" in job.description_clean
    assert job.posting_date is not None
    assert job.original_url == "https://www.goodwork.ca/jobs/construction-manager-jobs-76937"


def test_goodwork_parser_minimal():
    parser = GoodworkParser()
    html_content = """
    <html>
    <head><title>Environmental Planner jobs | GoodWork</title></head>
    <body>
    <section id="page">
    <p>General environmental planning duties.</p>
    </section>
    </body>
    </html>
    """
    raw = RawGoodworkJob(
        url="https://www.goodwork.ca/jobs/environmental-planner-12345",
        job_id="12345",
        html_content=html_content,
    )
    job = parser.parse_job(raw)
    assert job is not None
    assert job.source_job_id == "12345"
    assert "Environmental Planner" in job.job_title
    assert job.company_name == "Undisclosed Organization"
    assert job.location_cleaned == "Canada"
    assert job.salary_disclosed is False
