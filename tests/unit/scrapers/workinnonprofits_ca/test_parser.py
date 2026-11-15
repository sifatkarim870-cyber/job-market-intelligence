"""Unit tests for the WorkInNonProfits (Canada) parser."""

from __future__ import annotations

from job_market_intel.scrapers.workinnonprofits_ca.models import (
    DiscoveredJobItem,
    RawWorkInNonProfitsJob,
)
from job_market_intel.scrapers.workinnonprofits_ca.parser import WorkInNonProfitsParser


def test_workinnonprofits_parser_standard() -> None:
    html_content = """
    <html>
      <body>
        <div id="central_content">
          <h4>Job Posting 113186</h4>
          <h3>Manager, Recovery &amp; Integration</h3>
          <p>Canadian Mental Health Association BC Division</p>
          <p>closes in 8 days (Mon, 23 Nov)</p>
          <div class="description">
            We are hiring a Manager for our Vancouver office.
            Key responsibilities:
            - Oversee program operations
            - Coordinate team efforts
            Qualifications:
            - Degree in relevant field
            - 5 years management experience
          </div>
        </div>
      </body>
    </html>
    """
    item = DiscoveredJobItem(
        url="https://workinnonprofits.ca/jobs/view/113186/E",
        job_id="113186",
        title="Manager, Recovery & Integration",
        employer="Canadian Mental Health Association BC Division",
        location="Vancouver BC",
        type_info="Full time - $78,149.00 - $112,340.00",
        deadline="Monday, 23 November 2026",
        pub_date="Sat, 14 Nov 2026 00:15:03 +0000",
    )
    raw = RawWorkInNonProfitsJob(item=item, html_content=html_content)

    parser = WorkInNonProfitsParser()
    cleaned = parser.parse_job(raw)

    assert cleaned is not None
    assert cleaned.source_job_id == "113186"
    assert cleaned.job_title == "Manager, Recovery & Integration"
    assert cleaned.company_name == "Canadian Mental Health Association BC Division"
    assert "Vancouver BC" in cleaned.location_cleaned
    assert "Canada" in cleaned.location_cleaned
    assert cleaned.salary_disclosed is True
    assert cleaned.salary_min == 78149.0
    assert cleaned.salary_max == 112340.0
    assert cleaned.currency_iso_code == "CAD"
    assert cleaned.pay_period == "yearly"
    assert cleaned.employment_type_code == "full_time"
    assert cleaned.posting_date is not None
    assert cleaned.closing_date is not None
    assert cleaned.word_count > 10


def test_workinnonprofits_parser_hourly_rate() -> None:
    html_content = """
    <div id="central_content">
      <h4>Job Posting 113185</h4>
      <h3>Child/Youth Care Worker</h3>
      <p>MpowR Community and Organizational Supports</p>
      <p>Full description duties and qualifications here.</p>
    </div>
    """
    item = DiscoveredJobItem(
        url="https://workinnonprofits.ca/jobs/view/113185/E",
        job_id="113185",
        title="Child/Youth Care Worker",
        employer="MpowR Community and Organizational Supports",
        location="Edmonton, AB",
        type_info="On-Call / Relief / Casual - $22.82 - $30.16/hr",
        deadline="Friday, 27 November 2026",
        pub_date="Fri, 13 Nov 2026 19:30:03 +0000",
    )
    raw = RawWorkInNonProfitsJob(item=item, html_content=html_content)

    parser = WorkInNonProfitsParser()
    cleaned = parser.parse_job(raw)

    assert cleaned is not None
    assert cleaned.salary_disclosed is True
    assert cleaned.salary_min == 22.82
    assert cleaned.salary_max == 30.16
    assert cleaned.pay_period == "hourly"
    assert cleaned.employment_type_code == "part_time"
