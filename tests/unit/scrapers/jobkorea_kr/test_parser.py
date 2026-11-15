"""Unit tests for the Jobkorea (South Korea) parser."""

from __future__ import annotations

from job_market_intel.scrapers.jobkorea_kr.models import RawJobkoreaJob
from job_market_intel.scrapers.jobkorea_kr.parser import JobkoreaParser


def test_jobkorea_parser_with_salary() -> None:
    html_content = """
    <html>
      <head>
        <title>쿠팡CLS 현장사무직(인사/행정/급여 담당자)채용 | 잡코리아</title>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "title": "쿠팡CLS 현장사무직(인사/행정/급여 담당자)채용",
          "description": "쿠팡로지스틱스서비스(유)에서 계약직 채용을 진행합니다.",
          "datePosted": "2026-11-13",
          "validThrough": "2027-11-12T15:00",
          "employmentType": "CONTRACTOR",
          "hiringOrganization": {
            "@type": "Organization",
            "name": "쿠팡로지스틱스서비스(유)"
          },
          "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "KRW",
            "value": {
              "@type": "QuantitativeValue",
              "unitText": "YEAR",
              "minValue": 35400000,
              "maxValue": 35400000
            }
          },
          "jobLocation": {
            "@type": "Place",
            "address": {
              "@type": "PostalAddress",
              "streetAddress": "서울 강남구 테헤란로 332 (역삼동, HJ타워) 9층"
            }
          }
        }
        </script>
      </head>
      <body>
        <div class="ml-auto w-[960px] [grid-area:content]">
          <h2>모집요강</h2>
          <p>모집분야 필드어드민 리더. 주 5일 스케줄 근무 (주/야간 3교대).</p>
          <p>지원자격 경력 경력무관 학력 학력무관.</p>
        </div>
      </body>
    </html>
    """
    raw = RawJobkoreaJob(
        url="https://www.jobkorea.co.kr/Recruit/GI_Read/50357470",
        job_id="50357470",
        html_content=html_content,
    )
    parser = JobkoreaParser()
    cleaned = parser.parse_job(raw)

    assert cleaned is not None
    assert cleaned.source_job_id == "50357470"
    assert cleaned.job_title == "쿠팡CLS 현장사무직(인사/행정/급여 담당자)채용"
    assert cleaned.company_name == "쿠팡로지스틱스서비스(유)"
    assert "서울 강남구" in cleaned.location_cleaned
    assert "South Korea" in cleaned.location_cleaned
    assert cleaned.employment_type_code == "contract"
    assert cleaned.salary_disclosed is True
    assert cleaned.salary_min == 35400000.0
    assert cleaned.salary_max == 35400000.0
    assert cleaned.currency_iso_code == "KRW"
    assert cleaned.pay_period == "yearly"
    assert str(cleaned.posting_date).startswith("2026-11-13")
    assert cleaned.closing_date is not None
    assert cleaned.word_count > 10


def test_jobkorea_parser_fallback_html() -> None:
    html_content = """
    <html>
      <head>
        <title>AI 소프트웨어 엔지니어 채용 - 테크스타</title>
      </head>
      <body>
        <div id="artDetail">
          <h1>AI 소프트웨어 엔지니어 채용</h1>
          <a class="company">테크스타</a>
          <p>위치 서울특별시 강남구 역삼동</p>
          <div class="skills">
            <span>Python</span>
            <span>PyTorch</span>
          </div>
          <p>정규직 포지션입니다. 자연어 처리 및 거대 언어 모델 서빙 경험자 우대.</p>
        </div>
      </body>
    </html>
    """
    raw = RawJobkoreaJob(
        url="https://www.jobkorea.co.kr/Recruit/GI_Read/99999999",
        job_id="99999999",
        html_content=html_content,
    )
    parser = JobkoreaParser()
    cleaned = parser.parse_job(raw)

    assert cleaned is not None
    assert cleaned.job_title == "AI 소프트웨어 엔지니어 채용"
    assert cleaned.company_name == "테크스타"
    assert "South Korea" in cleaned.location_cleaned
    assert cleaned.employment_type_code == "full_time"
    assert "Python" in cleaned.skills
    assert cleaned.salary_disclosed is False
