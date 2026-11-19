"""Unit tests for the JobNet (Myanmar) parser."""

from __future__ import annotations

from job_market_intel.scrapers.jobnet_mm.models import RawJobnetJob
from job_market_intel.scrapers.jobnet_mm.parser import JobnetParser


def test_jobnet_parser_with_json_ld() -> None:
    """Full JobPosting JSON-LD with known field values."""
    html_content = """
    <html>
      <head>
        <title>Procurement Assistant | JobNet.com.mm</title>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "Title": "Procurement Assistant",
          "Description": "<p>Responsible for procurement, vendor management, and supply chain coordination. Requirements: degree in business or supply chain, min 2 years experience, good command of English and Microsoft Excel.</p>",
          "datePosted": "11/18/2026 10:16:11 AM",
          "validThrough": "1/16/2027 10:16:11 AM",
          "employmentType": "Full Time",
          "hiringOrganization": {
            "@type": "Organization",
            "name": "Future Bright Company Limited"
          },
          "jobLocation": {
            "@type": "Place",
            "address": {
              "@type": "PostalAddress",
              "addressLocality": "Yangon",
              "addressRegion": "Yangon",
              "addressCountry": "Myanmar"
            }
          },
          "identifier": {
            "@type": "PropertyValue",
            "Name": "Future Bright Company Limited",
            "Value": "2026111810161172834"
          }
        }
        </script>
      </head>
      <body>
        <h1>Procurement Assistant</h1>
        <div class="company-name">Future Bright Company Limited</div>
      </body>
    </html>
    """
    raw = RawJobnetJob(
        url="https://www.jobnet.com.mm/job/procurement-assistant-future-bright-company-limited/140310",
        job_id="140310",
        html_content=html_content,
    )
    parser = JobnetParser()
    cleaned = parser.parse_job(raw)

    assert cleaned is not None
    assert cleaned.source_job_id == "140310"
    assert cleaned.job_title == "Procurement Assistant"
    assert cleaned.company_name == "Future Bright Company Limited"
    assert "Yangon" in cleaned.location_cleaned
    assert "Myanmar" in cleaned.location_cleaned
    assert cleaned.employment_type_code == "full_time"
    assert cleaned.salary_disclosed is False
    assert cleaned.currency_iso_code == "MMK"
    assert cleaned.pay_period == "monthly"
    assert str(cleaned.posting_date).startswith("2026-11-18")
    assert cleaned.closing_date is not None
    assert str(cleaned.closing_date).startswith("2027-01-16")
    assert cleaned.word_count > 10
    assert "English" in cleaned.skills or "Excel" in cleaned.skills


def test_jobnet_parser_fallback_html() -> None:
    """No JSON-LD — falls back to HTML extraction."""
    html_content = """
    <html>
      <head>
        <title>Software Engineer | JobNet.com.mm</title>
      </head>
      <body>
        <h1>Software Engineer</h1>
        <div class="company-name">Tech Myanmar Co Ltd</div>
        <div class="job-location">Mandalay</div>
        <div class="job-description">
          We need a Python developer with SQL and Java experience.
          Good communication skills required. 2+ years experience needed.
        </div>
      </body>
    </html>
    """
    raw = RawJobnetJob(
        url="https://www.jobnet.com.mm/job/software-engineer-tech-myanmar/139999",
        job_id="139999",
        html_content=html_content,
    )
    parser = JobnetParser()
    cleaned = parser.parse_job(raw)

    assert cleaned is not None
    assert cleaned.job_title == "Software Engineer"
    assert "Myanmar" in cleaned.location_cleaned
    assert cleaned.salary_disclosed is False
    assert cleaned.currency_iso_code == "MMK"
    assert "Python" in cleaned.skills or "Java" in cleaned.skills or "Sql" in cleaned.skills


def test_jobnet_parser_batch() -> None:
    """parse_jobs handles a list including a malformed entry gracefully."""
    good_html = """
    <html><head><script type="application/ld+json">
    {"@context": "https://schema.org", "@type": "JobPosting",
     "Title": "Accountant", "datePosted": "11/15/2026 9:00:00 AM",
     "validThrough": "1/13/2027 9:00:00 AM",
     "employmentType": "Full Time",
     "hiringOrganization": {"@type": "Organization", "name": "Myanmar Finance Ltd"},
     "jobLocation": {"@type": "Place", "address": {
       "@type": "PostalAddress", "addressLocality": "Yangon",
       "addressRegion": "Yangon", "addressCountry": "Myanmar"
     }},
     "Description": "Prepare monthly accounts and financial statements. Accounting degree required."
    }
    </script></head><body></body></html>
    """
    raw_good = RawJobnetJob(
        url="https://www.jobnet.com.mm/job/accountant-myanmar-finance/140200",
        job_id="140200",
        html_content=good_html,
    )
    raw_empty = RawJobnetJob(
        url="https://www.jobnet.com.mm/job/empty/000000",
        job_id="000000",
        html_content="<html><body></body></html>",
    )

    parser = JobnetParser()
    results = parser.parse_jobs([raw_good, raw_empty])

    # Both should produce results (empty falls back to placeholder title)
    assert len(results) == 2
    assert results[0].job_title == "Accountant"
    assert results[0].company_name == "Myanmar Finance Ltd"
    assert str(results[0].posting_date).startswith("2026-11-15")
    assert results[1].job_title != ""  # fallback title set
