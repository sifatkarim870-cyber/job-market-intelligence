"""Unit tests for the Job.com.bd parser."""

from __future__ import annotations

from job_market_intel.scrapers.job_com_bd.models import RawJobComBdJob
from job_market_intel.scrapers.job_com_bd.parser import JobComBdParser


def test_job_com_bd_parser_standard() -> None:
    html_content = """
    <html>
      <head>
        <title>Chinese Interpreter / Translator - Majestic Materials Industries Ltd.</title>
      </head>
      <body>
        <div class="jd-wrapper">
          <div class="jd-title-block">
            <div class="jd-company">
              <a href="https://job.com.bd/employers/28635">Majestic Materials Industries Ltd.</a>
            </div>
            <h1 class="jd-title">Chinese Interpreter / Translator</h1>
            <div class="jd-badges">
              <span class="jd-badge jd-badge-blue">Full time</span>
              <span class="jd-badge jd-badge-purple">General / Others</span>
            </div>
            <div class="jd-posted">Posted 1 hour ago · 4 views</div>
          </div>
          <div class="jd-main">
            <div class="jd-card">
              <div class="jd-fact">
                <div class="jd-fact-label">Employment Type</div>
                <div class="jd-fact-value">Full time</div>
              </div>
              <div class="jd-fact">
                <div class="jd-fact-label">Job Location</div>
                <div class="jd-fact-value">Chattogram, Dhaka</div>
              </div>
              <div class="jd-fact">
                <div class="jd-fact-label">Salary</div>
                <div class="jd-fact-value">35,000 - 50,000 BDT</div>
              </div>
              <div class="jd-fact">
                <div class="jd-fact-label">Application Deadline</div>
                <div class="jd-fact-value">25 November, 2026</div>
              </div>
            </div>
            <div class="jd-card">
              <div class="jd-card-head">Job Responsibilities</div>
              <div class="jd-card-body">
                <p>Provide accurate interpretation and translation between Chinese and English/Bengali.</p>
                <p>Facilitate communication across departments and management teams.</p>
              </div>
            </div>
            <div class="jd-card">
              <div class="jd-card-head">Requirements</div>
              <div class="jd-card-body">
                <p>HSK Level 5 or higher proficiency in Mandarin Chinese.</p>
                <p>Bachelor degree in any discipline.</p>
              </div>
            </div>
            <div class="jd-skills">
              <span>Translation</span>
              <span>Interpretation</span>
              <span>Mandarin</span>
            </div>
          </div>
        </div>
      </body>
    </html>
    """
    raw = RawJobComBdJob(
        url="https://job.com.bd/jobs/chinese-interpreter-translator-l6hyov",
        job_id="l6hyov",
        html_content=html_content,
    )
    parser = JobComBdParser()
    cleaned = parser.parse_job(raw)

    assert cleaned is not None
    assert cleaned.source_job_id == "l6hyov"
    assert cleaned.job_title == "Chinese Interpreter / Translator"
    assert cleaned.company_name == "Majestic Materials Industries Ltd."
    assert "Chattogram, Dhaka" in cleaned.location_cleaned
    assert "Bangladesh" in cleaned.location_cleaned
    assert cleaned.salary_disclosed is True
    assert cleaned.salary_min == 35000.0
    assert cleaned.salary_max == 50000.0
    assert cleaned.currency_iso_code == "BDT"
    assert cleaned.pay_period == "monthly"
    assert cleaned.employment_type_code == "full_time"
    assert "Translation" in cleaned.skills
    assert cleaned.closing_date is not None
    assert cleaned.word_count > 20
