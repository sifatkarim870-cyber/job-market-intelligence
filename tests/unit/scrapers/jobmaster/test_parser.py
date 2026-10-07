"""Unit tests for the JobMaster html-only detail parser.

The fixture HTML below is a deliberately-trimmed verbatim excerpt of
a live detail page (job 9884960, 2026-10-07) — the same contract the
real scraper relies on. Inline on purpose: this HTML is the
contract; keeping it next to the assertions makes a site shape
change a one-place fix.
"""

from __future__ import annotations

import pytest

from job_market_intel.scrapers.jobmaster.models import RawJobmasterJob

DETAIL_HTML = """
<html><body>
<ul><li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">
  <a itemprop="item" href="/jobs/q-מחשבים-ותוכנה/">
    <span itemprop="name">מחשבים ותוכנה</span></a>
</li><li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">
  <a itemprop="item" href="/jobs/q-QA/">
    <span itemprop="name">QA</span></a>
</li></ul>
<article id="misra9884960" class="CardStyle articleJob JobItem font14">
  <div class="article__jobHead">
    <div class="jobHead__text">
      <div><div class="jobHead__text__titleAndCompName">
        <div class="CardHeader" style="padding-bottom:4px;">QA</div>
      </div></div>
    </div>
    <div class="jobHead__text__moreInfo"><div><div class="jobHead__text__title">
      <a class="font14 CompanyNameLink"
         href="/jobs/checkhevra.asp?cs=JETBNO" target="_blank">
        <span>מעבר למשרות נוספות קומבלק איי.טי. בע"מ</span>
      </a>
      <div class="jobHead__text__addedBefore"> פורסם לפני 16 דקות </div>
    </div></div></div>
    <div class="jobHead__text__img">
      <a href="/jobs/checkhevra.asp?cs=JETBNO&insite_ref=modaaLogo">
        <img alt="קומבלק איי.טי. בע&quot;מ"
             src="/jobs/imageurl.asp?cs=JETBNO" />
      </a>
    </div>
    <div class="JobExtraInfo" data-len="80"><ul>
      <li tabindex="0" class="jobLocation" id="jobLocationData">
        <span> איירפורט סיטי</span></li>
      <li tabindex="0" class="jobType">משרה מלאה</li>
      <li class="jobSalary" data-testtt="tt " title="שכר"> לא צוין שכר</li>
    </ul></div>
  </div>
  <div class="article__jobBody">
    <div class="jobDescription">
      <div class="peoplePJ"><div class="peoplePJ--metapel">
        <a class="peoplePJ--metapel--personLink">
          <div class="peoplePJ--metapel_details--text">
<div class="peoplePJ--metapel_details--text__korotTitle"
     data-test="tt">קומבלק איי.טי. בע&quot;מ</div>
          </div>
        </a>
      </div></div>
      <div class="JobItemSubHeader">תיאור המשרה: </div>
      <div id="jobDescriptionContent">תיאור QA.</div>
    </div>
    <div class="jobRequirements">
      <div class="JobItemSubHeader jobRequirements">דרישות המשרה: </div>
      <div id="jobRequirementsContent" style="text-align:start" dir="rtl">- ניסיון - JIRA</div>
    </div>
  </div>
</article>
</body></html>
"""


class TestFromPageHtml:
    def test_parses_body_fields(self) -> None:
        raw = RawJobmasterJob.from_page_html(
            DETAIL_HTML, original_url="https://www.jobmaster.co.il/jobs/checknum.asp?key=9884960"
        )
        assert raw.source_job_id == "9884960"
        assert raw.job_title == "QA"
        assert raw.company_name.startswith("קומבלק")
        assert raw.work_type_label == "משרה מלאה"
        assert raw.location_text == "איירפורט סיטי"
        assert raw.salary_text == "לא צוין שכר"
        assert raw.category_raws == ["מחשבים ותוכנה", "QA"]
        assert raw.description_html is not None
        assert "JIRA" in raw.description_html
        assert "דרישות" in raw.description_html

    def test_relative_date_resolves(self) -> None:
        raw = RawJobmasterJob.from_page_html(
            DETAIL_HTML, original_url="https://www.jobmaster.co.il/jobs/checknum.asp?key=9884960"
        )
        assert raw.posting_date is not None
        # 16 דקות ≈ minutes ago — the estimate must be very recent.
        from datetime import UTC, datetime, timedelta

        assert raw.posting_date >= datetime.now(UTC) - timedelta(hours=2)
        assert raw.closing_date is None

    def test_blocked_page_raises(self) -> None:
        with pytest.raises(ValueError):
            RawJobmasterJob.from_page_html(
                "<html><title>account</title></html>",
                original_url="https://www.jobmaster.co.il/jobs/checknum.asp?key=1",
            )

    def test_parser_never_raises_and_skips_bad_records(self) -> None:
        from job_market_intel.scrapers.jobmaster.parser import JobmasterParser

        parsed = JobmasterParser().parse_jobs(
            [
                {
                    "url": "https://www.jobmaster.co.il/jobs/checknum.asp?key=9884960",
                    "html": DETAIL_HTML,
                },
                {
                    "url": "https://www.jobmaster.co.il/jobs/checknum.asp?key=2",
                    "html": "<html>no article</html>",
                },
            ]
        )
        assert len(parsed) == 1
        assert parsed[0].source_job_id == "9884960"
