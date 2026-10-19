"""Unit tests for the JobsIreland.ie scraper (Ireland).

Pinned measured facts (2026-10-19, off live HTTP responses):

  * The site is an **Orchard CMS** application and is **server-rendered**: the
    listing fragment and the detail page both come back complete in a plain
    ``requests`` GET. **No browser is used.**
  * The listing endpoint is ``/Jobsireland.API/JobsIreland/BrowseJobs`` and
    answers ``content-type: text/html`` -- an HTML fragment, not JSON. It
    honours ``pageSize`` exactly; the full page returns ``pageSize + 1``.
  * **No filter parameters may be sent.** The site's own ``searchVacancy()``
    sends ``ContractTypeId=-1`` among six, and that set returns **zero** cards.
  * Every listing field is a hidden input: ``JobId``, ``JobReference``,
    ``CompanyLogo``, ``JobTitle``, ``Location``, ``StartDate``, ``EndDate``,
    ``VacancyTypeId``.
  * The listing title embeds the employer:
    ``"Pool Attendant  - CE Scheme - Graiguecullen / Killeshin Parish Co. Ltd"``.
  * Detail metadata is labelled by ``img.alt``: ``Image for Employer``,
    ``Image for Closing``, and so on. Class names are almost entirely absent.
  * Descriptions (``.job-description``) ran 645-1,268 chars over 14 postings,
    median 800, 0/14 under 400. The bare ``<pre>`` bound to Description ran
    87-818 with 8/14 under 200.
  * **No salary anywhere**: ``alt="Image for Euro"`` labels a link to a
    programme-wide rates page.
  * The board served "0 job found" transiently for several minutes during
    development, so an empty listing is retried, not believed.

No test touches the network. Fixtures are trimmed captures of the real markup.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from job_market_intel.cleaning.jobsireland_cleaner import (
    JobsIrelandCleaner,
    storable_closing_date,
    strip_artifact_lines,
    vacancy_employment_type,
)
from job_market_intel.scrapers.jobsireland.client import JobsIrelandClient
from job_market_intel.scrapers.jobsireland.config import JobsIrelandSettings
from job_market_intel.scrapers.jobsireland.exceptions import (
    JobsIrelandParseError,
    JobsIrelandResponseError,
)
from job_market_intel.scrapers.jobsireland.parser import (
    JobsIrelandParser,
    parse_detail,
    parse_iso_date,
    parse_listing,
    parse_long_date,
    reduce_location,
    split_listing_title,
)

#: Real captured values, verbatim. Held as constants because the markup lines
#: carrying them run past the project's line-length limit, and abbreviating
#: them would weaken the very parsing being tested.
POOL_TITLE = "Pool Attendant  - CE Scheme - Graiguecullen / Killeshin Parish Co. Ltd"
POOL_LOCATION = "Graiguecullen Swiming Pool, Chaff St, Graiguecul, Carlow, Co. Carlow, R93 N5Y0"
LOGO = "https://jobseeker.jobsireland.ie/Branding/dsp/Avatar.png"
#: The employer pasted their whole listing title into the ad title, so the
#: detail <h3> legitimately repeats the company. Preserved rather than "fixed".
LONG_TITLE = (
    "Environmental Worker - Stradbally Tidy Towns - Ce Scheme - Tay Valley CLG "
    "- CE Scheme - Tay Valley CLG "
)
LONG_LOCATION = "Stradbally Village , Stradbally, Waterford, X42 DT89"

#: The listing fragment's shape: hidden inputs, flat, one set per card, with a
#: trailing card and the site's own share buttons around them.
LISTING = f"""<div class="job-list full paginated job-description-box" id="joblisting-box">
<div class="social-innner"><div class="a2a_kit"><a>Map</a><a>Share/Print</a></div></div>
<input type="hidden" id="JobId" value="2475745" />
<input type="hidden" id="JobReference" value="#CES-2475745" />
<input type="hidden" id="CompanyLogo" value="" />
<input type="hidden" id="JobTitle" value="{POOL_TITLE}" />
<input type="hidden" id="Location" value="{POOL_LOCATION}" />
<input type="hidden" id="StartDate" value="2026-10-19T12:05:30" />
<input type="hidden" id="EndDate" value="2026-11-30T00:00:00" />
<input type="hidden" id="VacancyTypeId" value="3" />
<input type="hidden" id="JobId" value="2471265" />
<input type="hidden" id="JobReference" value="#CES-2471265" />
<input type="hidden" id="CompanyLogo" value="{LOGO}" />
<input type="hidden" id="JobTitle" value="{LONG_TITLE}" />
<input type="hidden" id="Location" value="{LONG_LOCATION}" />
<input type="hidden" id="StartDate" value="2026-10-19T11:53:59" />
<input type="hidden" id="EndDate" value="2026-11-02T00:00:00" />
<input type="hidden" id="VacancyTypeId" value="0" />
</div>"""

#: A detail page. The <pre> bound to Description is deliberately SHORT (the
#: wrong node to use) while .job-description is long (the right one), because
#: that difference is why the validator's threshold is 400 and not 200.
DETAIL = f"""<html><body>
<div class="job_details_box"><div class="row job_details_box_inner">
<div class="job-details">
  <h3>Pool Attendant (Seasonal)</h3>
  <img alt="Logo of JobsIreland" />
  <ul class="job-detail_list">
    <li><img alt="Image for Employer" />Graiguecullen / Killeshin Parish Co. Ltd</li>
    <li><img alt="Decorative" /></li>
    <li><img alt="Image for Job Ref" />Ref: #CES-2475745</li>
    <li><img alt="Image for Location" />{POOL_LOCATION}</li>
    <li><img alt="Image Position" />No of positions: 3</li>
    <li><img alt="Image Part Time" />Community Employment Programme</li>
    <li><img alt="Image Hours per week" />19.5 hours per week</li>
    <li><img alt="Image for Euro" />Community Employment Programme Rates</li>
    <li><img alt="Image for Published" />Published On: 19 Oct 2026</li>
    <li><img alt="Image for Closing" />Closing On: 30 Nov 2026</li>
  </ul>
  <div class="button emp-btn">Register your interest</div>
</div>
<div class="col-md-8">
  <div class="job-inner-box">
    <div class="social-innner">
      <div class="share-group shareClick">
        <div class="social-icons"><a>Map</a><a>Share/Print</a>
        <a>copy link</a><a>Generate PDF</a></div>
      </div>
    </div>
    <div class="social-innner"><div><h3>Job Description</h3></div></div>
    <span><h5><strong>Duties</strong></h5></span>
    <p>This is a developmental opportunity, no experience necessary.</p>
    <pre ng-bind-html="Description | linky" class="ng-binding">
Pool Attendant
</pre>
    <div class="job-description">
      <div class="social-innner"><div class="social-icons"><a>Map</a>
      <a>Share/Print</a><a>copy link</a><a>Generate PDF</a></div></div>
      <div class="share-group shareClick">share</div>
      <h4>Application Details</h4>
      <p>Eligibility to participate on CE is generally linked to those who are 21
      years or over and in receipt of a qualifying social welfare payment for 1
      year or more or 18 years and over for certain disadvantaged groups. Your
      eligibility will have to be verified by the Department.</p>
      <p>To register your interest you can contact an Employment Personal Advisor
      (EPA) in your local Intreo Centre.</p>
      <h4>Application Method</h4>
      <p>Applicants should supply suitable character references and be prepared to
      complete a Garda vetting application form.</p>
      <h4>Duties</h4>
      <p>This is a developmental opportunity, no experience necessary. Accredited
      training will be provided to support your career.</p>
      <p>Duties include pool lifeguard cover, pool maintenance, cleaning of changing
      rooms, and general maintenance of the facility.</p>
      <p>Sector:</p>
    </div>
  </div>
</div>
</div></div></body></html>"""

PARSER = JobsIrelandParser()
HINT = {
    "JobId": "2475745",
    "JobReference": "#CES-2475745",
    "CompanyLogo": "",
    "JobTitle": "Pool Attendant  - CE Scheme - Graiguecullen / Killeshin Parish Co. Ltd",
    "Location": "Graiguecullen Swiming Pool, Chaff St, Graiguecul, Carlow, Co. Carlow, R93 N5Y0",
    "StartDate": "2026-10-19T12:05:30",
    "EndDate": "2026-11-30T00:00:00",
    "VacancyTypeId": "3",
    "page": 1,
}


def _detail(html: str = DETAIL, ad_id: str = "2475745", hint: dict | None = None):
    return parse_detail(
        ad_id,
        html,
        url=f"https://jobsireland.ie/en-US/job-Details?id={ad_id}",
        listing_page=1,
        hint=hint if hint is not None else HINT,
    )


# ---------------------------------------------------------------- listing


class TestListingCards:
    def test_cards_come_out_of_the_flat_hidden_inputs(self):
        cards = parse_listing(LISTING, 1)
        assert set(cards) == {"2475745", "2471265"}
        assert cards["2475745"]["JobReference"] == "#CES-2475745"
        assert cards["2471265"]["VacancyTypeId"] == "0"

    def test_the_page_number_is_recorded(self):
        assert parse_listing(LISTING, 7)["2475745"]["page"] == 7

    def test_near_miss_inputs_are_ignored(self):
        """The page has many other hidden inputs; only the eight count."""
        cards = parse_listing(LISTING, 1)
        assert all(
            not set(c)
            - {
                "JobId",
                "JobReference",
                "CompanyLogo",
                "JobTitle",
                "Location",
                "StartDate",
                "EndDate",
                "VacancyTypeId",
                "page",
            }
            for c in cards.values()
        )

    def test_an_empty_fragment_yields_nothing(self):
        assert parse_listing("<div>nothing here</div>", 1) == {}

    def test_a_trailing_card_without_a_closing_div_is_still_captured(self):
        html = (
            '<input type="hidden" id="JobId" value="9" />'
            '<input type="hidden" id="JobTitle" value="X" />'
        )
        assert "9" in parse_listing(html, 1)


class TestListingTitleSplitting:
    def test_the_employer_comes_out_and_the_scheme_goes(self):
        title, company = split_listing_title(
            "Pool Attendant  - CE Scheme - Graiguecullen / Killeshin Parish Co. Ltd"
        )
        assert title == "Pool Attendant"
        assert company == "Graiguecullen / Killeshin Parish Co. Ltd"

    def test_a_title_with_no_scheme_shape_is_left_alone(self):
        title, company = split_listing_title("Software Engineer")
        assert title == "Software Engineer"
        assert company is None

    def test_an_employer_name_containing_ltd_is_not_mistaken_for_a_scheme(self):
        """'Co. Ltd' is a company suffix, not the 'Co.' county prefix."""
        title, company = split_listing_title("Cleaner - CE Scheme - ACME Ltd")
        assert title == "Cleaner" and company == "ACME Ltd"

    @pytest.mark.parametrize(
        "scheme",
        [
            "CE Scheme",
            "WPEP",
            "Community Employment",
            "Paid Position",
            "Apprenticeship",
            "Self Employed",
        ],
    )
    def test_every_programme_name_is_recognised(self, scheme):
        title, company = split_listing_title(f"Barista - {scheme} - Somewhere Ltd")
        assert title == "Barista" and company == "Somewhere Ltd"


# ---------------------------------------------------------------- location


class TestReduceLocation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # county carries the "Co." prefix -> town, county
            ("COOLE HALL, Coole, Co. Westmeath, N91 E525", "Coole, Co. Westmeath"),
            (
                "CLÁR I.R.D., Ballyhaunis Road, Claremorris, Co. Mayo, F12 KV29",
                "Claremorris, Co. Mayo",
            ),
            ("Galbally, Co. Limerick, ", "Galbally, Co. Limerick"),
            ("Co. Tipperary,", "Co. Tipperary"),
            ("Kiniska, Claregalway, Galway,", "Claregalway, Galway"),
            # no "Co." prefix -> the town is SECOND-to-last, not last
            ("Stradbally Village , Stradbally, Waterford, X42 DT89", "Stradbally, Waterford"),
            # bare city, with and without a Dublin postal district
            ("Dublin 2", "Dublin 2"),
            ("Dublin 12", "Dublin 12"),
            ("Galway,", "Galway"),
        ],
    )
    def test_addresses_reduce_to_town_and_county(self, raw, expected):
        assert reduce_location(raw) == expected

    def test_the_town_is_not_the_county_when_there_is_no_co_prefix(self):
        """The bug this shape caused: the last part IS the county."""
        assert (
            reduce_location("Stradbally Village , Stradbally, Waterford, X42 DT89") != "Waterford"
        )

    def test_a_bare_premises_name_is_not_a_location(self):
        assert reduce_location("COOLE HALL") is None

    def test_a_street_only_address_is_not_a_location(self):
        assert reduce_location("45 George's St Upr, Blackcourt Road") is None

    @pytest.mark.parametrize("blank", ["", None, "   ", ",", " , , "])
    def test_blank_input_is_none(self, blank):
        assert reduce_location(blank) is None

    def test_the_eircode_is_never_kept_as_a_place(self):
        out = reduce_location(
            "Graiguecullen Swiming Pool, Chaff St, Graiguecul, Carlow, Co. Carlow, R93 N5Y0"
        )
        assert "R93" not in out and "N5Y0" not in out


# ---------------------------------------------------------------- detail


class TestDetailFields:
    def test_the_title_has_no_employer_in_it(self):
        job = _detail()
        assert job.title == "Pool Attendant (Seasonal)"
        assert "Graiguecullen" not in job.title

    def test_the_detail_heading_wins_over_the_listing_title(self):
        """The two are deliberately DIFFERENT in this fixture.

        The detail page's ``<h3>`` is the title alone; the listing's
        ``JobTitle`` still carries " - CE Scheme - <employer>". Setting them
        equal made the two code paths indistinguishable, so "prefer the
        detail heading" was unpinned -- ignoring the heading outright and
        falling back still produced the right answer.
        """
        job = _detail()
        assert job.title == "Pool Attendant (Seasonal)"
        assert job.title != split_listing_title(HINT["JobTitle"])[0], (
            "the fixture no longer distinguishes the two paths"
        )
        assert job.listing_title == HINT["JobTitle"], "the listing copy is kept for audit"

    def test_the_employer_is_read_from_its_own_icon(self):
        assert _detail().company_name == "Graiguecullen / Killeshin Parish Co. Ltd"

    def test_the_reference_positions_and_hours_come_out(self):
        job = _detail()
        assert job.reference == "#CES-2475745"
        assert job.positions == 3
        assert job.hours_per_week == "19.5 hours per week"

    def test_dates_come_from_the_hidden_inputs(self):
        job = _detail()
        assert job.posted_date == date(2026, 10, 19)
        assert job.closing_date == date(2026, 11, 30)

    def test_the_vacancy_type_is_labelled_from_its_id(self):
        job = _detail()
        assert job.vacancy_type_id == "3"
        assert job.vacancy_type_label == "Community Employment Programme"

    def test_the_address_is_stored_both_ways(self):
        job = _detail()
        assert "R93 N5Y0" in job.location, "the raw address is kept"
        assert job.location_reduced == "Carlow, Co. Carlow"

    def test_a_missing_h3_falls_back_to_the_listing_title(self):
        html = DETAIL.replace("<h3>Pool Attendant (Seasonal)</h3>", "")
        job = _detail(html)
        assert job.title == "Pool Attendant", "the scheme and employer are split back out"
        assert job.company_name == "Graiguecullen / Killeshin Parish Co. Ltd"

    def test_neither_h3_nor_listing_title_raises(self):
        html = DETAIL.replace("<h3>Pool Attendant (Seasonal)</h3>", "")
        with pytest.raises(JobsIrelandParseError, match="markup changed"):
            _detail(html, hint={"VacancyTypeId": "3"})


class TestDescription:
    def test_the_description_node_is_used_not_the_short_pre(self):
        """The <pre> bound to Description is 13 chars here; .job-description
        is several hundred. Using the <pre> would fail validation on most rows
        -- measured 8 of 14 live postings under 200 chars that way."""
        job = _detail()
        assert len(job.description) > 400

    def test_the_real_body_is_kept(self):
        # The fixture wraps its prose across source lines, so compare on
        # whitespace-normalised text rather than on the raw run.
        desc = re.sub(r"\s+", " ", _detail().description)
        assert "pool lifeguard cover" in desc
        assert "Accredited training" in desc
        assert "qualifying social welfare payment" in desc
        assert "Employment Personal Advisor" in desc

    def test_the_share_block_is_gone(self):
        desc = _detail().description
        assert "Generate PDF" not in desc
        assert "Share/Print" not in desc
        assert "copy link" not in desc
        assert not re.search(r"\bMap\b", desc)

    def test_the_job_description_heading_label_is_gone(self):
        assert "Job Description" not in _detail().description

    def test_the_trailing_sector_label_is_gone(self):
        assert not re.search(r"^Sector:$", _detail().description, re.M)

    def test_a_page_with_no_description_node_yields_none(self):
        html = DETAIL.replace('class="job-description"', 'class="gone"')
        assert _detail(html).description is None


class TestNoSalary:
    def test_the_euro_icon_does_not_become_a_salary(self):
        """alt='Image for Euro' labels a link to a programme rates page."""
        job = _detail()
        assert job.raw["rates_label"] == "Community Employment Programme Rates"
        cleaned = JobsIrelandCleaner().clean_job(job)
        assert cleaned.salary_min is None and cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_no_salary_row_is_written_even_though_pay_period_is_set(self):
        cleaned = JobsIrelandCleaner().clean_job(_detail())
        assert cleaned.pay_period == "hourly"
        assert cleaned.currency_iso_code == "EUR"
        assert not cleaned.salary_disclosed


# ---------------------------------------------------------------- dates


class TestDates:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2026-10-19T12:05:30", date(2026, 10, 19)),
            ("2026-11-02T00:00:00", date(2026, 11, 2)),
            ("Published On: 19 Oct 2026", date(2026, 10, 19)),
            ("Closing On: 30 Nov 2026", date(2026, 11, 30)),
            ("", None),
            (None, None),
            ("not a date", None),
            ("2026-13-45T00:00:00", None),
        ],
    )
    def test_both_date_shapes_parse(self, value, expected):
        got = parse_iso_date(value)
        if got is None and isinstance(value, str) and ":" in value:
            got = parse_long_date(value)
        assert got == expected

    def test_the_time_component_is_dropped_not_kept(self):
        """StartDate is the moment the posting was last touched, not a date."""
        assert parse_iso_date("2026-10-19T12:05:30") == date(2026, 10, 19)


# ---------------------------------------------------------------- cleaner


class TestCleaner:
    def test_location_is_the_reduced_form_not_the_postal_address(self):
        cleaned = JobsIrelandCleaner().clean_job(_detail())
        assert cleaned.location_cleaned == "Carlow, Co. Carlow"
        assert "R93" not in cleaned.location_cleaned

    def test_the_raw_address_is_kept_in_the_payload(self):
        cleaned = JobsIrelandCleaner().clean_job(_detail())
        assert "R93 N5Y0" in cleaned.raw_payload["address_raw"]

    def test_metadata_survives_into_the_payload(self):
        payload = JobsIrelandCleaner().clean_job(_detail()).raw_payload
        assert payload["reference"] == "#CES-2475745"
        assert payload["positions"] == 3
        assert payload["hours_per_week"] == "19.5 hours per week"
        assert payload["vacancy_type_label"] == "Community Employment Programme"

    def test_word_count_matches_the_description(self):
        cleaned = JobsIrelandCleaner().clean_job(_detail())
        assert cleaned.word_count == len(cleaned.description_clean.split())

    def test_url_and_id_are_carried(self):
        cleaned = JobsIrelandCleaner().clean_job(_detail())
        assert cleaned.source_job_id == "2475745"
        assert cleaned.original_url.endswith("job-Details?id=2475745")

    @pytest.mark.parametrize(
        ("vacancy_id", "expected"),
        [
            ("0", "full_time"),
            ("3", "part_time"),
            ("4", "apprenticeship"),
            ("6", "freelance"),
            ("10", "internship"),
            ("-1", None),
            (None, None),
        ],
    )
    def test_vacancy_types_map_to_employment_types(self, vacancy_id, expected):
        assert vacancy_employment_type(vacancy_id) == expected

    def test_artifact_stripping_keeps_the_prose(self):
        assert "pool lifeguard" in strip_artifact_lines(
            "pool lifeguard\nImage for Employer\nRef: #CES-1\ncover"
        )
        assert "Image for" not in strip_artifact_lines("a\nImage for Employer\nb")


class TestClosingDateGuard:
    def test_a_deadline_before_the_posting_is_dropped(self):
        assert storable_closing_date(date(2026, 10, 19), date(2026, 10, 1)) is None

    def test_a_deadline_after_the_posting_is_kept(self):
        assert storable_closing_date(date(2026, 10, 19), date(2026, 11, 30)) == date(2026, 11, 30)

    def test_no_posting_date_keeps_the_deadline(self):
        assert storable_closing_date(None, date(2026, 11, 30)) == date(2026, 11, 30)

    def test_the_cleaner_applies_it(self):
        job = _detail()
        job.posted_date = date(2026, 10, 19)
        job.closing_date = date(2026, 10, 1)
        assert JobsIrelandCleaner().clean_job(job).closing_date is None

    def test_a_real_pair_survives_the_cleaner(self):
        cleaned = JobsIrelandCleaner().clean_job(_detail())
        assert cleaned.posting_date == datetime(2026, 10, 19)
        assert cleaned.closing_date == datetime(2026, 11, 30)


# ---------------------------------------------------------------- client


class TestClientContract:
    def test_no_browser_is_configured_anywhere(self):
        settings = JobsIrelandSettings()
        assert settings.list_api_path == "/Jobsireland.API/JobsIreland/BrowseJobs"
        assert not hasattr(settings, "headless"), "this source needs no browser"

    def test_the_list_url_sends_no_filters(self):
        """ContractTypeId=-1 alone empties the listing; the URL must stay bare."""
        url = JobsIrelandClient(JobsIrelandSettings()).list_url(2)
        assert url == (
            "https://jobsireland.ie/Jobsireland.API/JobsIreland/BrowseJobs?page=2&pageSize=50"
        )
        for banned in (
            "ContractTypeId",
            "VacancyTypeId",
            "vacancyId",
            "CareerlevelId",
            "keyWord",
            "location",
        ):
            assert banned not in url

    def test_the_detail_url_takes_the_numeric_id(self):
        url = JobsIrelandClient(JobsIrelandSettings()).detail_url("2475745")
        assert url.endswith("/en-US/job-Details?id=2475745")

    def test_an_empty_discovery_raises_rather_than_looking_successful(self):
        client = JobsIrelandClient(JobsIrelandSettings())
        client.fetch_listing = lambda page=1: {}
        with pytest.raises(JobsIrelandResponseError, match="0 job found"):
            client.discover()

    def test_an_empty_page_is_retried_before_it_is_believed(self):
        """The board served '0 job found' for minutes, then recovered.

        The distinguishing signal is the NUMBER of listing requests: believing
        the first empty page stops after one, retrying keeps going. Asserting
        only that a raise happens left those two paths indistinguishable --
        both raise, so the mutation passed.
        """
        client = JobsIrelandClient(
            JobsIrelandSettings(empty_listing_retries=2, empty_listing_backoff_seconds=0)
        )
        client._listing_is_genuinely_empty = lambda: False
        calls = []

        def fake(page=1):
            calls.append(page)
            return {}

        client.fetch_listing = fake
        with pytest.raises(JobsIrelandResponseError):
            client.discover()
        assert len(calls) > 1, (
            f"the empty listing was believed immediately after {len(calls)} "
            "request(s); it must be retried first"
        )
        client.close()

    def test_a_genuinely_empty_board_stops_immediately(self):
        client = JobsIrelandClient(JobsIrelandSettings(empty_listing_backoff_seconds=0))
        client._listing_is_genuinely_empty = lambda: True
        calls = []

        def fake(page=1):
            calls.append(page)
            return {}

        client.fetch_listing = fake
        with pytest.raises(JobsIrelandResponseError):
            client.discover()
        assert calls == [1], "it must not keep hammering an empty board"
        client.close()

    def test_a_detail_page_without_the_block_is_named_as_a_failure(self):
        client = JobsIrelandClient(JobsIrelandSettings(inter_request_delay_seconds=0))
        client._get = lambda url, ajax=False: "<html><body>nothing</body></html>"
        assert client.fetch_detail("1") is None
        client.close()
