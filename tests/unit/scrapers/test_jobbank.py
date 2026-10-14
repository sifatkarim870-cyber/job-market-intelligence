"""Unit tests for the Job Bank Canada scraper.

Each test pins a bug found while building this source against the live site,
which is how every other scraper's tests here are written. All four were found
by running the real thing, not by reading it:

  1. ``h1`` is NOT the job title. For a posting surfaced by the term
     "developer", h1 is literally "developer" -- the board echoes the search
     term back. The title is the line after "Title posted on <board> -".
  2. The first ``dd`` element is the OCCUPATION's median wage
     ("50.26 $/hour"), not this job's pay. The real figure
     ("$96,557 to $128,743 annually") is in the body. Reading the median wage
     wrote a plausible, wrong salary into every row.
  3. "annually" is not a valid pay_period. The schema admits only
     hourly/daily/weekly/monthly/yearly, and the violation aborts the
     transaction, so one wrong value cost the entire run (0 inserted, 30
     failed, all from a single posting).
  4. An inline ``Employer: value`` regex returned the string "s" because it
     matched the heading "Employers" with the label "employer". Job Bank puts
     labels and values on consecutive lines.

Run with:  uv run pytest tests/unit/scrapers/test_jobbank.py -q
"""

from __future__ import annotations

from datetime import date

import pytest

from job_market_intel.cleaning.jobbank_cleaner import JobBankCleaner
from job_market_intel.scrapers.jobbank.client import JobBankClient
from job_market_intel.scrapers.jobbank.exceptions import JobBankParseError
from job_market_intel.scrapers.jobbank.parser import JobBankParser, _parse_money

# Trimmed from a real posting page fetched 2026-10-14 (posting 50483505).
REAL_HTML = """
<html><body>
<h1>developer</h1>
<div class="job-posting-details">
software developer
Title posted on Talent.com -
Sr Software Developer (Lead) - EN 178
Posted on
                October 12, 2026
by
Employer details
Export Development Canada | Exportation et d&#233;veloppement Canada
Location:
All of Canada
Salary: $96,557 to $128,743 annually
Application deadline: Oct 23 12:00 PM ET
We are looking for a senior developer to build internal data tooling.
</div>
<dl><dt>Median wage Help -</dt><dd>50.26 $/hour</dd>
    <dt>Date modified:</dt><dd>2026-08-18</dd></dl>
</body></html>
"""

#: The schema's own vocabulary. Nothing outside this set may reach
#: salary.job_salaries.pay_period.
ALLOWED_PERIODS = {"hourly", "daily", "weekly", "monthly", "yearly"}


class TestUrlShape:
    def test_search_url_carries_term_and_page(self):
        url = JobBankClient().search_url("software developer", 3)
        assert "term=software+developer" in url
        assert "page=3" in url
        assert "sort=" in url

    def test_posting_url_uses_the_numeric_id_only(self):
        """The live URL also carries a rotating jsessionid; identity must not."""
        assert JobBankClient().posting_url("50483505").endswith("/jobposting/50483505")


class TestParserTitle:
    def test_title_is_not_the_search_term(self):
        """Bug 1: h1 echoes the query, so it must not be trusted."""
        job = JobBankParser().parse("1", REAL_HTML)
        assert job.title == "Sr Software Developer (Lead) - EN 178"
        assert job.title != "developer"

    def test_falls_back_to_h1_when_no_title_line(self):
        html = "<html><body><h1>Real Title</h1><div class='job-posting-details'>"
        html += "x" * 400 + "</div></body></html>"
        assert JobBankParser().parse("1", html).title == "Real Title"

    def test_no_title_at_all_raises(self):
        """A posting with no title is not a posting; do not return it empty."""
        with pytest.raises(JobBankParseError):
            JobBankParser().parse("1", "<html><body><div>no title here</div></body></html>")


class TestParserSalary:
    def test_median_wage_is_not_used_as_the_salary(self):
        """Bug 2: the dd/dt pair is occupational furniture, not the job's pay."""
        job = JobBankParser().parse("1", REAL_HTML)
        assert job.salary_min == 96557
        assert job.salary_max == 128743
        assert job.salary_min != 50.26

    def test_pay_period_is_valid_for_the_schema(self):
        """Bug 3: "annually" violates ck_job_salaries_pay_period."""
        job = JobBankParser().parse("1", REAL_HTML)
        assert job.pay_period in ALLOWED_PERIODS
        assert job.pay_period == "yearly"

    @pytest.mark.parametrize(
        "text,expected_period",
        [
            ("$50.00 hourly", "hourly"),
            ("50.26 $/hour", "hourly"),
            ("$1,200 weekly", "weekly"),
            ("$5,000 per month", "monthly"),
            ("$96,557 to $128,743 annually", "yearly"),
            ("$70,000 a year", "yearly"),
        ],
    )
    def test_money_parsing_covers_every_period(self, text, expected_period):
        _lo, _hi, period = _parse_money(text)
        assert period in ALLOWED_PERIODS
        assert period == expected_period

    def test_no_salary_yields_none_rather_than_guessing(self):
        html = (
            "<html><body><h1>Title</h1><div class='job-posting-details'>"
            + "y" * 400
            + "</div></body></html>"
        )
        job = JobBankParser().parse("1", html)
        assert job.salary_min is None


class TestParserFields:
    def test_employer_is_the_line_after_its_label(self):
        """Bug 4: an inline regex returned "s" from the heading "Employers"."""
        job = JobBankParser().parse("1", REAL_HTML)
        assert job.employer.startswith("Export Development Canada")
        assert job.employer != "s"

    def test_location_is_captured(self):
        assert JobBankParser().parse("1", REAL_HTML).location == "All of Canada"

    def test_posted_and_deadline_dates(self):
        job = JobBankParser().parse("1", REAL_HTML)
        assert job.posted_date == date(2026, 10, 12)
        assert job.deadline_date == date(2026, 10, 23)

    def test_date_modified_is_not_mistaken_for_the_deadline(self):
        """2026-08-18 is the page's "Date modified", earlier than the posting."""
        job = JobBankParser().parse("1", REAL_HTML)
        assert job.deadline_date != date(2026, 8, 18)


class TestCleaner:
    def _job(self):
        return JobBankParser().parse(
            "50483505", REAL_HTML, url="https://www.jobbank.gc.ca/jobsearch/jobposting/50483505"
        )

    def test_cleaned_job_carries_the_schema_vocabulary(self):
        """The failure that cost a whole run must not be reachable again."""
        cleaned = JobBankCleaner().clean_job(self._job())
        assert cleaned.pay_period in ALLOWED_PERIODS
        assert cleaned.source_job_id == "50483505"

    def test_bilingual_employer_keeps_one_name(self):
        """Keeping "A | B" would create a second company entity for one employer."""
        cleaned = JobBankCleaner().clean_job(self._job())
        assert "|" not in cleaned.company_name
        assert cleaned.company_name == "Export Development Canada"

    def test_salary_flag_follows_the_figure(self):
        cleaned = JobBankCleaner().clean_job(self._job())
        assert cleaned.salary_disclosed is True
        assert cleaned.salary_min == 96557
        assert cleaned.salary_max == 128743

    def test_currency_is_cad(self):
        assert JobBankCleaner().clean_job(self._job()).currency_iso_code == "CAD"

    def test_clean_jobs_logs_rather_than_silently_returning_nothing(self):
        """The version that caught every exception with no output reported
        "Cleaned: 0" on every run and gave no clue why."""

        class Exploding:
            source_job_id = "1"

            def __getattr__(self, _name):
                raise RuntimeError("boom")

        assert JobBankCleaner().clean_jobs([Exploding()]) == []  # does not raise


class TestValidator:
    def test_posted_date_is_a_required_field(self):
        """An aggregator mirror going stale would otherwise pass unnoticed."""
        from job_market_intel.validation.jobbank_validator import _MISSING_FIELD_CHECKS

        assert "posted_date" in _MISSING_FIELD_CHECKS

        class NoDate:
            source_job_id = "1"
            title = "t"
            description = "d" * 200
            employer = "e"
            url = "u"
            posted_date = None

        assert _MISSING_FIELD_CHECKS["posted_date"](NoDate()) is True
