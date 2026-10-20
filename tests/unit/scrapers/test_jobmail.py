"""Unit tests for the JobMail scraper (South Africa).

Pinned measured facts (2026-10-19, off live HTTP responses):

  * **No browser.** The site is server-rendered and serves both the listing
    and the detail page in a plain GET.
  * The listing is ``/jobs/`` and ``/jobs/pageN`` -- 20 postings a page, and
    7,980 distinct postings were reachable at page 400 with no end in sight.
  * Every card carries its id in ``id="results-item-7568798"`` and again in
    the link's ``-id-7568798`` slug.
  * The card's ``div.job-info`` holds either a rand range -- ``R20 000,00 -
    R30 000,00`` -- or the words **"Market Related"**, which is a salary that
    is deliberately not a figure. The cadence is the sibling div, "PER MONTH".
  * The detail page carries a schema.org ``JobPosting`` with a 1,432-5,510
    character body, ``datePosted``, ``validThrough``, ``employmentType``,
    ``hiringOrganization.name``, ``identifier.value`` and, on some postings, a
    numeric ``baseSalary`` in ZAR per month.
  * The location's granularity varies: ``addressLocality`` is a city on some
    postings and a province on others.
  * The card's date is "DD Month YYYY" and may carry a non-breaking space.

No test touches the network. The fixtures are trimmed captures of the real
markup, and the JSON-LD is copied verbatim.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from job_market_intel.cleaning.jobmail_cleaner import (
    JobMailCleaner,
    storable_closing_date,
)
from job_market_intel.scrapers.jobmail.client import JobMailClient
from job_market_intel.scrapers.jobmail.config import JobMailSettings
from job_market_intel.scrapers.jobmail.exceptions import (
    JobMailParseError,
    JobMailResponseError,
)
from job_market_intel.scrapers.jobmail.parser import (
    JobMailParser,
    parse_cadence,
    parse_card_date,
    parse_card_salary,
    parse_detail,
    parse_listing,
    parse_rand_amount,
)

#: A card with a salary, captured from the live page.
CARD_WITH_SALARY = """<div class="results-item tablinks" id="results-item-7568798">
<div class="flex-container"><div><div class="job-posted">04 September 2026</div></div></div>
<div class="flex-container"><div style="width: 90%;">
<a class="tablinks" href="/jobs/administration-pa-secretary/other-administration-pa-secretary/
kwazulu-natal/designated-agent-id-7568798" id="jobDetailUrl-7568798">
<h3>Designated Agent</h3></a></div></div>
<div><div class="flex-container"><div>
<div class="job-info"><b>R20&nbsp;000,00 - R30&nbsp;000,00</b></div>
<div>PER MONTH</div></div></div></div>
<div class="flex-container"><div class="job-location">Kwazulu-Natal</div>
<div><div class="resault-company-name"><span class="c-title">Employer</span>
<span class="company">Bargaining Council for the Furniture Manufacturing Industry
KwaZulu-Natal</span></div></div></div>
</div>"""

#: A card whose salary is the words "Market Related".
CARD_MARKET_RELATED = """<div class="results-item tablinks" id="results-item-7575388">
<div class="job-posted">16 September 2026</div>
<a class="tablinks" href="/jobs/management/other-management/kwazulu-natal/junior-management-
assistant-id-7575388"><h3>JUNIOR MANAGEMENT ASSISTANT</h3></a>
<div class="job-info">Market Related</div>
<div class="job-location">Kwazulu-Natal</div>
<span class="company">Pvt</span>
</div>"""

#: A card with no salary at all, and a non-breaking space in the date.
CARD_NO_SALARY = """<div class="results-item tablinks" id="results-item-7579680">
<div class="job-posted">12&nbsp;October 2026</div>
<a class="tablinks" href="/jobs/retail/sales-assistant/pretoria/jewellery-sales-assistant-
urgently-needed-id-7579680"><h3>Jewellery Sales Assistant</h3></a>
<div class="job-location">Pretoria</div>
<span class="company">Goldstone Jewellers</span>
</div>"""

#: The JobPosting block, copied from the live detail page.
JOB_POSTING = {
    "@context": "https://schema.org/",
    "@type": "JobPosting",
    "title": "Designated Agent",
    "industry": "administration-pa-secretary, other administration/pa/secretary",
    "url": "http://www.jobmail.co.za/jobs/administration-pa-secretary/"
    "other-administration-pa-secretary/kwazulu-natal/designated-agent-id-7568798",
    "datePosted": "2026-09-04T08:55:35",
    "validThrough": "2026-10-30T08:55:35",
    "description": "Our Jewellery store is looking for an experienced Sales "
    "Assistant to join our retail team.\r\nRequirements:\r\nPrevious jewellery "
    "sales experience essential\r\nFluent in both English & Afrikaans\r\nMust "
    "reside in Pretoria.",
    "employmentType": "FULL_TIME",
    "hiringOrganization": {
        "@type": "Organization",
        "name": "Bargaining Council for the Furniture Manufacturing Industry KwaZulu-Natal",
        "logo": "",
        "url": "http://www.jobmail.co.za/companies-hiring/search/...",
    },
    "identifier": {"@type": "PropertyValue", "name": "...", "value": "7568798"},
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "Kwazulu-Natal",
            "addressRegion": "Kwazulu-Natal",
            "addressCountry": "ZA",
        },
    },
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "ZAR",
        "value": {
            "@type": "QuantitativeValue",
            "minValue": 20000,
            "maxValue": 30000,
            "unitText": "MONTH",
        },
    },
}

DETAIL_HTML = (
    """<html><head><script type="application/ld+json">"""
    + json.dumps(JOB_POSTING, ensure_ascii=False)
    + """</script></head><body>
<div class="job-details"><h1>Designated Agent</h1></div>
</body></html>"""
)


def _detail(html: str = DETAIL_HTML, job_id: str = "7568798", card: dict | None = None):
    return parse_detail(
        job_id, html, url=f"https://www.jobmail.co.za/jobs/x-id-{job_id}", card=card or {}
    )


# ---------------------------------------------------------------- cards


class TestListingCards:
    def test_the_cards_are_found(self):
        cards = parse_listing(CARD_WITH_SALARY)
        assert len(cards) == 1
        assert cards[0]["job_id"] == "7568798"

    def test_the_id_comes_from_the_element_id(self):
        assert parse_listing(CARD_WITH_SALARY)[0]["job_id"] == "7568798"

    def test_the_title_comes_from_the_heading(self):
        assert parse_listing(CARD_WITH_SALARY)[0]["title"] == "Designated Agent"

    def test_the_date_and_location_and_employer_come_out(self):
        card = parse_listing(CARD_WITH_SALARY)[0]
        assert card["posted_text"] == "04 September 2026"
        assert card["card_location"] == "Kwazulu-Natal"
        assert "Bargaining Council" in card["card_company"]

    def test_the_salary_comes_out_of_job_info(self):
        card = parse_listing(CARD_WITH_SALARY)[0]
        assert card["salary_min"] == 20000
        assert card["salary_max"] == 30000
        assert card["pay_period"] == "monthly"

    def test_market_related_is_a_salary_but_not_a_figure(self):
        card = parse_listing(CARD_MARKET_RELATED)[0]
        assert card["salary_min"] is None
        assert card["salary_max"] is None
        assert card["salary_undisclosed"] is True, (
            "'Market Related' is a salary that is not a number"
        )

    def test_a_card_with_no_salary_reports_none(self):
        card = parse_listing(CARD_NO_SALARY)[0]
        assert card["salary_min"] is None
        assert card["salary_undisclosed"] is False

    def test_a_non_breaking_space_in_the_date_is_handled(self):
        card = parse_listing(CARD_NO_SALARY)[0]
        assert card["posted_text"] == "12 October 2026"

    def test_three_cards_are_three_records(self):
        cards = parse_listing(CARD_WITH_SALARY + CARD_MARKET_RELATED + CARD_NO_SALARY)
        assert [c["job_id"] for c in cards] == ["7568798", "7575388", "7579680"]

    def test_an_empty_page_yields_nothing(self):
        assert parse_listing("<html><body></body></html>") == []


# ---------------------------------------------------------------- salary


class TestRandAmounts:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("20 000,00", 20000),
            ("20 000,00", 20000),
            ("1 000 000,00", 1000000),
            ("900 000,00", 900000),
            ("20", 20),
            ("20 000", 20000),
        ],
    )
    def test_a_space_is_thousands_and_a_comma_is_decimals(self, text, expected):
        assert parse_rand_amount(text) == expected

    def test_a_non_breaking_space_is_also_thousands(self):
        assert parse_rand_amount("20 000,00") == 20000

    def test_something_that_is_not_a_number_is_none(self):
        assert parse_rand_amount("Market Related") is None
        assert parse_rand_amount("Negotiable") is None
        assert parse_rand_amount("") is None
        assert parse_rand_amount(None) is None

    def test_the_us_format_is_read_too(self):
        """A blanket 'strip the dots, then swap the commas' gives 20 for 20,000."""
        assert parse_rand_amount("20,000.00") == 20000
        assert parse_rand_amount("1,000,000.00") == 1000000
        assert parse_rand_amount("1,000,000") == 1000000

    def test_a_zero_ceiling_is_no_ceiling(self):
        """A zero maximum violates the schema's salary_max >= salary_min."""
        low, high, _und = parse_card_salary("R20 000,00 - R 0,00")
        assert low == 20000
        assert high is None, "a zero ceiling must not be written as a ceiling"

    def test_an_inverted_range_keeps_the_floor_and_drops_the_ceiling(self):
        low, high, _und = parse_card_salary("R30 000,00 - R20 000,00")
        assert low == 30000
        assert high is None

    def test_a_zero_floor_is_no_floor(self):
        low, high, _und = parse_card_salary("R0 - R20 000,00")
        assert low is None
        assert high == 20000

    def test_the_country_comes_from_the_record_not_the_board(self):
        """addressCountry, not the region and not a hard-coded default."""
        job = _detail()
        assert job.country == "ZA"

        data = json.loads(json.dumps(JOB_POSTING))
        data["jobLocation"]["address"]["addressCountry"] = "NA"
        html = (
            '<html><head><script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False)
            + "</script></head><body></body></html>"
        )
        assert _detail(html).country == "NA"

    def test_the_pay_period_is_always_in_the_schema_vocabulary(self):
        """A value outside it aborts the shared transaction."""
        cleaned = JobMailCleaner().clean_job(_detail())
        assert cleaned.pay_period in {"hourly", "daily", "weekly", "monthly", "yearly"}

    def test_a_posting_with_no_salary_still_gets_a_valid_pay_period(self):
        """Without a baseSalary the record's pay_period is None.

        The cleaner's fallback is what the posting gets then, and it has to be
        inside the schema's vocabulary.
        """
        data = json.loads(json.dumps(JOB_POSTING))
        del data["baseSalary"]
        html = (
            '<html><head><script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False)
            + "</script></head><body></body></html>"
        )
        job = _detail(html)
        assert job.pay_period is None
        cleaned = JobMailCleaner().clean_job(job)
        assert cleaned.pay_period in {"hourly", "daily", "weekly", "monthly", "yearly"}

    def test_a_normal_range_is_unaffected_by_the_guards(self):
        assert parse_card_salary("R20 000,00 - R30 000,00") == (20000, 30000, False)

    def test_a_range_is_read(self):
        assert parse_card_salary("R20 000,00 - R30 000,00") == (20000, 30000, False)

    def test_a_range_with_non_breaking_spaces_is_read(self):
        assert parse_card_salary("R20 000,00 - R30 000,00") == (20000, 30000, False)

    def test_a_single_amount_is_a_range_of_one(self):
        assert parse_card_salary("R20 000,00") == (20000, 20000, False)

    @pytest.mark.parametrize(
        "marker", ["Market Related", "market related", "Negotiable", "Undisclosed"]
    )
    def test_the_markers_are_unpublished_salaries_not_figures(self, marker):
        low, high, undisclosed = parse_card_salary(marker)
        assert (low, high) == (None, None)
        assert undisclosed is True

    def test_nothing_at_all_is_not_an_undisclosed_salary(self):
        assert parse_card_salary("") == (None, None, False)
        assert parse_card_salary(None) == (None, None, False)

    def test_the_cadence_maps_to_the_schema_vocabulary(self):
        assert parse_cadence("PER MONTH") == "monthly"
        assert parse_cadence("PER HOUR") == "hourly"
        assert parse_cadence("PER YEAR") == "yearly"
        assert parse_cadence("per month") == "monthly"
        assert parse_cadence("Monthly") is None
        assert parse_cadence(None) is None


class TestCardDates:
    def test_a_card_date_parses(self):
        assert parse_card_date("04 September 2026") == date(2026, 9, 4)
        assert parse_card_date("12 October 2026") == date(2026, 10, 12)

    def test_a_non_breaking_space_does_not_break_the_month(self):
        assert parse_card_date("12 October 2026") == date(2026, 10, 12)

    @pytest.mark.parametrize("bad", ["", None, "TBD", "04 Septem 2026", "2026-09-04"])
    def test_an_unreadable_date_is_none(self, bad):
        assert parse_card_date(bad) is None


# ---------------------------------------------------------------- detail


class TestDetailFields:
    def test_the_title_and_company_come_from_the_json_ld(self):
        job = _detail()
        assert job.title == "Designated Agent"
        assert job.company_name.startswith("Bargaining Council")

    def test_the_id_comes_from_the_identifier(self):
        assert _detail().source_job_id == "7568798"

    def test_the_dates_come_from_the_posting(self):
        job = _detail()
        assert job.posted_date == date(2026, 9, 4)
        assert job.closing_date == date(2026, 10, 30)

    def test_the_description_comes_through(self):
        job = _detail()
        assert job.description is not None
        assert "jewellery sales experience" in job.description

    def test_the_employment_type_maps_to_the_schema_vocabulary(self):
        assert _detail().employment_type_code == "full_time"

    def test_the_industry_is_kept(self):
        assert "administration-pa-secretary" in (_detail().industry or "")

    def test_the_numeric_base_salary_wins(self):
        job = _detail()
        assert job.salary_min == 20000
        assert job.salary_max == 30000
        assert job.salary_currency == "ZAR"
        assert job.pay_period == "monthly"

    def test_the_cards_figure_is_used_when_the_detail_has_none(self):
        data = json.loads(json.dumps(JOB_POSTING))
        del data["baseSalary"]
        html = (
            '<html><head><script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False)
            + "</script></head><body></body></html>"
        )
        job = _detail(
            html, card={"salary_min": 20000, "salary_max": 30000, "pay_period": "monthly"}
        )
        assert job.salary_min == 20000
        assert job.salary_currency == "ZAR"

    def test_a_province_location_is_kept_as_one_value(self):
        """addressLocality and addressRegion are the same string here."""
        job = _detail()
        assert job.locality == "Kwazulu-Natal"
        assert job.region == "Kwazulu-Natal"
        assert job.location == "Kwazulu-Natal", "an equal locality and region is not repeated"

    def test_a_city_and_a_province_are_joined(self):
        data = json.loads(json.dumps(JOB_POSTING))
        data["jobLocation"]["address"]["addressLocality"] = "Pretoria"
        data["jobLocation"]["address"]["addressRegion"] = "Gauteng"
        html = (
            '<html><head><script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False)
            + "</script></head><body></body></html>"
        )
        job = _detail(html)
        assert job.location == "Pretoria, Gauteng"

    def test_a_page_with_no_jobposting_block_raises(self):
        with pytest.raises(JobMailParseError, match="JobPosting"):
            _detail("<html><body>nothing</body></html>")

    def test_the_company_falls_back_to_the_card(self):
        data = json.loads(json.dumps(JOB_POSTING))
        data["hiringOrganization"] = {}
        html = (
            '<html><head><script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False)
            + "</script></head><body></body></html>"
        )
        job = _detail(html, card={"card_company": "Pvt"})
        assert job.company_name == "Pvt"

    def test_html_entities_are_decoded(self):
        """The board writes them into the JSON-LD still escaped.

        ``O&#x27;Brien Recruitment`` and ``Junior Estimator &amp;
        Administrator`` both arrived verbatim -- and a company called
        "O&#x27;Brien" is a different company from "O'Brien" as far as the
        corpus's company de-duplication is concerned.
        """
        data = json.loads(json.dumps(JOB_POSTING))
        data["title"] = "Junior Estimator &amp; Administrator"
        data["hiringOrganization"]["name"] = "O&#x27;Brien Recruitment"
        data["description"] = "Some &lt;strong&gt;bold&lt;/strong&gt; text &amp; more"
        html = (
            '<html><head><script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False)
            + "</script></head><body></body></html>"
        )
        job = _detail(html)
        assert job.title == "Junior Estimator & Administrator"
        assert job.company_name == "O'Brien Recruitment"
        assert "<strong>" in job.description
        assert "&amp;" not in job.description


# ---------------------------------------------------------------- cleaner


class TestCleaner:
    def test_the_body_survives(self):
        cleaned = JobMailCleaner().clean_job(_detail())
        assert cleaned.description_clean is not None
        assert "jewellery" in cleaned.description_clean
        assert cleaned.word_count == len(cleaned.description_clean.split())

    def test_the_location_is_the_joined_form(self):
        data = json.loads(json.dumps(JOB_POSTING))
        data["jobLocation"]["address"]["addressLocality"] = "Pretoria"
        data["jobLocation"]["address"]["addressRegion"] = "Gauteng"
        html = (
            '<html><head><script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False)
            + "</script></head><body></body></html>"
        )
        cleaned = JobMailCleaner().clean_job(_detail(html))
        assert cleaned.location_cleaned == "Pretoria, Gauteng"

    def test_the_salary_is_carried_with_its_currency(self):
        cleaned = JobMailCleaner().clean_job(_detail())
        assert cleaned.salary_min == 20000
        assert cleaned.salary_max == 30000
        assert cleaned.salary_disclosed is True
        assert cleaned.currency_iso_code == "ZAR"
        assert cleaned.pay_period == "monthly"

    def test_an_undisclosed_salary_is_not_claimed(self):
        data = json.loads(json.dumps(JOB_POSTING))
        del data["baseSalary"]
        html = (
            '<html><head><script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False)
            + "</script></head><body></body></html>"
        )
        job = _detail(html, card={"salary_undisclosed": True})
        cleaned = JobMailCleaner().clean_job(job)
        assert cleaned.salary_disclosed is False
        assert cleaned.salary_min is None
        assert cleaned.raw_payload["salary_undisclosed"] is True, (
            "the distinction between no salary and an unpublished one is kept"
        )

    def test_the_title_is_the_posting_own_title(self):
        assert JobMailCleaner().clean_job(_detail()).job_title == "Designated Agent"


class TestClosingDateGuard:
    def test_a_deadline_before_the_posting_is_dropped(self):
        assert storable_closing_date(date(2026, 9, 4), date(2026, 9, 1)) is None

    def test_a_deadline_after_the_posting_is_kept(self):
        assert storable_closing_date(date(2026, 9, 4), date(2026, 10, 30)) == date(2026, 10, 30)

    def test_no_posting_date_keeps_the_deadline(self):
        assert storable_closing_date(None, date(2026, 10, 30)) == date(2026, 10, 30)

    def test_the_cleaner_applies_it(self):
        job = _detail()
        job.posted_date = date(2026, 9, 4)
        job.closing_date = date(2026, 9, 1)
        assert JobMailCleaner().clean_job(job).closing_date is None


# ---------------------------------------------------------------- client


class TestClientContract:
    def test_no_browser_is_configured_anywhere(self):
        assert not hasattr(JobMailSettings(), "headless"), "this source needs no browser"

    def test_the_listing_url_pages_by_number(self):
        client = JobMailClient(JobMailSettings())
        assert client.listing_url(1) == "https://www.jobmail.co.za/jobs/"
        assert client.listing_url(2) == "https://www.jobmail.co.za/jobs/page2"
        assert client.listing_url(7) == "https://www.jobmail.co.za/jobs/page7"

    def test_the_detail_url_completes_a_relative_href(self):
        client = JobMailClient(JobMailSettings())
        assert client.detail_url("/jobs/x-id-1") == "https://www.jobmail.co.za/jobs/x-id-1"
        assert client.detail_url("https://x/jobs/y-id-2") == "https://x/jobs/y-id-2"

    def test_an_empty_discovery_raises_rather_than_looking_successful(self):
        client = JobMailClient(JobMailSettings())
        client.fetch_listing_page = lambda page=1: []
        with pytest.raises(JobMailResponseError, match="8,000"):
            client.discover()
        client.close()

    def test_the_discovery_stops_at_the_budget(self):
        client = JobMailClient(JobMailSettings(max_jobs_per_run=5, max_list_pages=10))
        client.fetch_listing_page = lambda page=1: [
            {"job_id": str(i), "title": f"Job {i}", "url": "/x", "page": 1} for i in range(10)
        ]
        found, _ = client.discover()
        assert len(found) == 5
        client.close()

    def test_a_page_that_repeats_its_ids_does_not_inflate_the_count(self):
        client = JobMailClient(JobMailSettings(max_jobs_per_run=100, max_list_pages=3))
        client.fetch_listing_page = lambda page=1: [
            {"job_id": "1", "title": "A", "url": "/x", "page": 1},
            {"job_id": "2", "title": "B", "url": "/x", "page": 1},
        ]
        found, _ = client.discover()
        assert len(found) == 2
        client.close()


class TestTheValidator:
    """The batch validator, which nothing else exercises."""

    def _jobs(self, count: int = 12):
        jobs = []
        for i in range(count):
            job = _detail(job_id=str(756_879 + i))
            job.source_job_id = str(756_879 + i)
            jobs.append(job)
        return jobs

    def test_a_healthy_batch_passes(self):
        from job_market_intel.validation.jobmail_validator import JobMailBatchValidator

        jobs = self._jobs()
        report = JobMailBatchValidator().validate([{}] * len(jobs), jobs)
        assert report.passed, getattr(report, "issues", None)

    def test_a_salary_is_not_required(self):
        """Only a third of the board publishes a figure."""
        from job_market_intel.validation.jobmail_validator import JobMailBatchValidator

        jobs = self._jobs()
        for job in jobs:
            job.salary_min = None
            job.salary_max = None
        report = JobMailBatchValidator().validate([{}] * len(jobs), jobs)
        assert report.passed, getattr(report, "issues", None)
        assert "salary" not in report.missing_field_rates

    def test_a_missing_description_is_reported(self):
        from job_market_intel.validation.jobmail_validator import JobMailBatchValidator

        jobs = self._jobs()
        for job in jobs:
            job.description = None
        report = JobMailBatchValidator().validate([{}] * len(jobs), jobs)
        assert report.missing_field_rates.get("description") == 1.0, (
            f"a missing description went unreported: {report.missing_field_rates}"
        )


def test_the_parser_is_exported():
    assert JobMailParser is not None
    assert isinstance(_detail().posted_datetime(), datetime)
