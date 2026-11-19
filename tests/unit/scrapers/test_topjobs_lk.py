"""Unit tests for the TopJobs (topjobs.lk, Sri Lanka) scraper.

Pinned measured facts (2026-11-20, live site):

  * Listing rows are clickable ``<tr onclick="createAlert(...)">`` elements,
    not anchors; the four codes in that call build the ad URL.
  * Seven cells: index, job code, position+employer, teaser, opening,
    closing, town.
  * Listing dates are ``Fri Nov 20 2026``; ad-page dates are ``03/12/2026``.
  * Listing titles carry trailing headcount (``"Sales  Representative  (10)"``);
    ad-page titles do not.
  * 71 of 75 sampled ads were image-only: ``#remark`` held an ``<img>`` and
    no text.
  * Ad-status labels observed: Full Time, Permanent, Onsite -- with Contract
    and Internship as the exceptions.

No test touches the network.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from job_market_intel.cleaning.topjobs_lk_cleaner import (
    TopJobsLkCleaner,
    map_employment_type,
    map_work_mode,
    storable_closing_date,
)
from job_market_intel.scrapers.topjobs_lk.client import TopJobsLkClient
from job_market_intel.scrapers.topjobs_lk.config import TopJobsLkSettings
from job_market_intel.scrapers.topjobs_lk.exceptions import TopJobsLkResponseError
from job_market_intel.scrapers.topjobs_lk.models import RawTopJobsLkJob
from job_market_intel.scrapers.topjobs_lk.parser import (
    detail_url,
    parse_detail,
    parse_detail_date,
    parse_listing,
    parse_listing_date,
    split_headcount,
)
from job_market_intel.validation.topjobs_lk_validator import (
    TopJobsLkBatchValidator,
    TopJobsLkValidationSettings,
)

TODAY = date(2026, 11, 20)

LISTING = """<!DOCTYPE html><html><body>
<table>
<thead><tr>
  <th>#</th><th id="jbrefno">Job Ref No.</th><th>Position and Employer</th>
  <th>Job Description</th><th>Opening Date</th><th>Closing Date</th><th>Town</th>
</tr></thead>
<tbody>
<tr id="tr0" onclick="createAlert('0','0000000419','0001573439','0000000552','TjGrTQ')">
  <td align="center" width="1%">1</td>
  <td align="center" width="5%">1573439</td>
  <td width="28%"><span hidden id="hdnJC0">0001573439</span>
    <h2><span>Call Center Executive  (20)</span></h2>
    <h1>Micronet Global Services (Pvt) Ltd</h1></td>
  <td width="35%">Urgent</td>
  <td width="12%">Fri Nov 20 2026</td>
  <td width="12%">Fri Nov 27 2026</td>
  <td width="8%">Battaramulla, Borella, Gampaha (Gampaha)</td>
</tr>
<tr id="tr1" onclick="createAlert('1','0000000419','0001573423','0000000552','TjGrTQ')">
  <td align="center" width="1%">2</td>
  <td align="center" width="5%">1573423</td>
  <td width="28%"><h2><span>Sales  Representative  (10)</span></h2>
    <h1>Micronet Global Services (Pvt) Ltd</h1></td>
  <td width="35%">Urgent</td>
  <td width="12%">Fri Nov 20 2026</td>
  <td width="12%">Fri Nov 27 2026</td>
  <td width="8%">Ambalangoda, Elpitiya, Imaduwa (Imaduwa), Kaduwela (Kaduwela)</td>
</tr>
<tr><td colspan="7">footer row with no posting</td></tr>
</tbody></table></body></html>"""

#: A text ad, shaped like the live page: title/employer/body/closing/ref plus
#: the ad-status label set.
DETAIL_TEXT = """<!DOCTYPE html><html><body>
<h3 id="position" class="col-xs-8 job-title">Junior Coordinator - Security and safety</h3>
<h5 id="employer" class="ad-company-name" title="Micronet Global Services (Pvt) Ltd">
  Micronet Global Services (Pvt) Ltd</h5>
<div class="ad-jb-detail">
  <label class="lbl-closing-date">Closing Date: <span id="endDate">20/11/2026</span></label>
  <label class="lbl-job-ref">Job Ref No: <span id="jobRefNum">1572306</span></label>
</div>
<div class="ad-status">
  <label class="lbl_fulltime">Full Time</label>
  <label class="lbl_fulltime">Permanent</label>
  <label class="lbl_fulltime">Onsite</label>
</div>
<div id="remark" class="job-holder">
  <p><strong>WE ARE HIRING!</strong></p>
  <p>We are looking for enthusiastic, responsible, and well-organized individuals
     to join our team as <strong>Junior Coordinator - Security and Safety!</strong>
     Previous security experience will be an added advantage. Working hours are
     12-hour shifts (day and night). Send your CV to hr3@micronetglobal.net.</p>
</div>
</body></html>"""

#: The common case: an ad whose body is one image and no text.
DETAIL_IMAGE = """<!DOCTYPE html><html><body>
<h3 id="position">Call Center Executive</h3>
<h5 id="employer">Micronet Global Services (Pvt) Ltd</h5>
<div class="ad-jb-detail">
  <label>Closing Date: <span id="endDate">27/11/2026</span></label>
  <label>Job Ref No: <span id="jobRefNum">1573439</span></label>
</div>
<div class="ad-status">
  <label class="lbl_fulltime">Full Time</label>
  <label class="lbl_fulltime">Onsite</label>
</div>
<div id="remark"><img src="../images/ads/1573439.jpg" alt="advertisement"/></div>
</body></html>"""

META = parse_listing(LISTING, 1)["0001573439"]


def _raw(**overrides) -> RawTopJobsLkJob:
    base = {
        "source_job_id": "0001573439",
        "title": "Call Center Executive",
        "company_name": "Micronet Global Services (Pvt) Ltd",
        "headcount": 20,
        "listing_snippet": "Urgent",
        "location": "Battaramulla, Borella, Gampaha (Gampaha)",
        "country": "Sri Lanka",
        "description": "We are looking for enthusiastic individuals to join our team.",
        "employment_type": "Full Time",
        "work_mode": "Onsite",
        "labels": ["Full Time", "Permanent", "Onsite"],
        "posted_date": TODAY,
        "closing_date": date(2026, 11, 27),
        "url": detail_url("https://topjobs.lk", "0", "0000000419", "0001573439", "0000000552"),
        "listing_page": 1,
        "raw": {"description_is_image": False},
    }
    base.update(overrides)
    return RawTopJobsLkJob(**base)


class TestListing:
    def test_rows_become_postings_keyed_on_the_job_code(self):
        cards = parse_listing(LISTING, 1)
        assert set(cards) == {"0001573439", "0001573423"}
        assert "footer row" not in " ".join(c["title"] for c in cards.values())

    def test_title_company_and_dates_come_off_the_row(self):
        card = parse_listing(LISTING, 1)["0001573423"]
        assert card["title"] == "Sales Representative"
        assert card["company"] == "Micronet Global Services (Pvt) Ltd"
        assert card["opening_raw"] == "Fri Nov 20 2026"
        assert card["closing_raw"] == "Fri Nov 27 2026"

    def test_country_and_town_are_not_confused(self):
        card = parse_listing(LISTING, 1)["0001573439"]
        assert card["town"] == "Battaramulla, Borella, Gampaha (Gampaha)"
        assert card["headcount"] == 20

    def test_the_detail_url_is_built_from_the_onclick_codes(self):
        card = parse_listing(LISTING, 1)["0001573439"]
        assert card["url"] == (
            "https://topjobs.lk/employer/JobAdvertismentServlet"
            "?rid=0&ac=0000000419&jc=0001573439&ec=0000000552"
            "&pg=applicant/vacancybyfunctionalarea.jsp"
        )
        assert "createAlert" not in card["url"]

    def test_a_page_of_chrome_yields_nothing_rather_than_inventing_postings(self):
        assert parse_listing("<html><body><table></table></body></html>") == {}

    def test_pagination_uses_page_no_and_page_one_does_not(self):
        client = TopJobsLkClient(TopJobsLkSettings())
        assert client.listing_url(1) == (
            "https://topjobs.lk/applicant/vacancybyfunctionalarea.jsp?jst=OPEN"
        )
        assert client.listing_url(2) == (
            "https://topjobs.lk/applicant/vacancybyfunctionalarea.jsp?jst=OPEN&pageNo=2"
        )

    def test_the_same_code_on_two_pages_is_one_posting(self):
        """Consecutive live pages overlap by exactly one row."""
        client = TopJobsLkClient(TopJobsLkSettings(max_listing_pages=2))
        pages = {1: LISTING, 2: LISTING}
        client.fetch_listing_page = lambda page=1: pages[page]
        found, failures = client.discover_listings()
        assert set(found) == {"0001573439", "0001573423"}
        assert failures == {}


class TestTitleHeadcount:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Sales  Representative  (10)", ("Sales Representative", 10)),
            ("Call Center Executive  (20)", ("Call Center Executive", 20)),
            ("Delivery Rider", ("Delivery Rider", None)),
            ("Engineer (Contract)", ("Engineer (Contract)", None)),
            ("Analyst (Night Shift) (3)", ("Analyst (Night Shift)", 3)),
        ],
    )
    def test_trailing_headcount_is_split_off(self, raw, expected):
        assert split_headcount(raw) == expected


class TestDates:
    def test_listing_format(self):
        assert parse_listing_date("Fri Nov 20 2026") == date(2026, 11, 20)

    def test_ad_page_format_is_day_first(self):
        assert parse_detail_date("03/12/2026") == date(2026, 12, 3)

    @pytest.mark.parametrize("bad", ["", None, "TBD", "20/13/2026", "Fri Nov 40 2026"])
    def test_unreadable_dates_are_none_not_today(self, bad):
        assert parse_listing_date(bad) is None
        assert parse_detail_date(bad) is None


class TestDetailMerge:
    def test_the_ad_page_title_wins_over_the_listing_title(self):
        meta = dict(META)
        meta["title"] = "WRONG LISTING TITLE"
        job = parse_detail(meta, DETAIL_IMAGE)
        assert job.title == "Call Center Executive"
        assert job.headcount == 20, "the listing's headcount must survive"

    def test_the_body_and_labels_come_from_the_ad_page(self):
        job = parse_detail(META, DETAIL_TEXT)
        assert job.description is not None
        assert "WE ARE HIRING" in job.description
        assert job.employment_type == "Full Time"
        assert job.work_mode == "Onsite"
        assert job.labels == ["Full Time", "Permanent", "Onsite"]

    def test_an_image_only_ad_is_recorded_as_such(self):
        job = parse_detail(META, DETAIL_IMAGE)
        assert job.description is None
        assert job.description_is_image is True
        assert job.raw["description_has_image"] is True

    def test_no_body_and_no_image_is_not_called_image_only(self):
        no_image = DETAIL_IMAGE.replace(
            '<img src="../images/ads/1573439.jpg" alt="advertisement"/>', ""
        )
        job = parse_detail(META, no_image)
        assert job.description is None
        assert job.description_is_image is False

    def test_a_failed_ad_fetch_still_yields_the_listing_record(self):
        job = parse_detail(META, None, listing_page=1)
        assert job.title == "Call Center Executive"
        assert job.company_name == "Micronet Global Services (Pvt) Ltd"
        assert job.posted_date == date(2026, 11, 20)
        assert job.closing_date == date(2026, 11, 27)
        assert job.location == "Battaramulla, Borella, Gampaha (Gampaha)"
        assert job.employment_type is None
        assert job.description_is_image is False

    def test_the_ad_page_closing_date_wins_over_the_listing(self):
        html = DETAIL_TEXT.replace("20/11/2026", "03/12/2026")
        job = parse_detail(META, html)
        assert job.closing_date == date(2026, 12, 3)

    def test_a_missing_ad_date_falls_back_to_the_listing(self):
        html = DETAIL_TEXT.replace("20/11/2026", "")
        job = parse_detail(META, html)
        assert job.closing_date == date(2026, 11, 27)

    def test_the_contract_label_is_kept_verbatim_for_the_cleaner(self):
        html = DETAIL_TEXT.replace("Full Time", "Contract").replace("Permanent", "Internship")
        job = parse_detail(META, html)
        assert job.employment_type == "Contract"


class TestClientWindow:
    def _cards(self, n: int) -> dict[str, dict]:
        return {f"{i:04d}": {"jc": f"{i:04d}", "url": f"u{i}", "page": 1} for i in range(n)}

    def test_a_budget_above_the_board_takes_everything(self):
        client = TopJobsLkClient(TopJobsLkSettings())
        assert len(client.select_window(self._cards(5), 10)) == 5

    def test_the_newest_rows_are_always_taken(self):
        client = TopJobsLkClient(TopJobsLkSettings(fresh_rows=3, start_offset=0))
        chosen = client.select_window(self._cards(10), 5)
        assert [c["jc"] for c in chosen] == ["0000", "0001", "0002", "0003", "0004"]

    def test_the_tail_window_rotates(self):
        client = TopJobsLkClient(TopJobsLkSettings(fresh_rows=2, start_offset=4))
        chosen = client.select_window(self._cards(10), 5)
        # 2 fresh + 3 from the tail starting at index 4 of [2..9]
        assert [c["jc"] for c in chosen] == ["0000", "0001", "0006", "0007", "0008"]

    def test_the_window_wraps_around_the_tail(self):
        client = TopJobsLkClient(TopJobsLkSettings(fresh_rows=0, start_offset=8))
        chosen = client.select_window(self._cards(10), 4)
        assert [c["jc"] for c in chosen] == ["0008", "0009", "0000", "0001"]

    def test_the_offset_advances_one_window_per_day(self):
        client = TopJobsLkClient(TopJobsLkSettings(fresh_rows=0))
        day = date.today().toordinal()
        assert client.rotation_offset(1000, 250) == (day * 250) % 1000

    def test_empty_discovery_raises_rather_than_returning_nothing(self):
        client = TopJobsLkClient(TopJobsLkSettings(max_listing_pages=1))
        client.fetch_listing_page = lambda page=1: "<html><body></body></html>"
        with pytest.raises(TopJobsLkResponseError, match="markup changed"):
            client.discover_listings()

    def test_records_can_be_fetched_without_ad_pages(self):
        client = TopJobsLkClient(TopJobsLkSettings(fetch_details=False))
        client.discover_listings = lambda: ({META["jc"]: META}, {})
        records, failures = client.fetch_raw_jobs()
        assert failures == {}
        assert records[0]["listing"]["jc"] == META["jc"]
        assert records[0]["detail_html"] is None


class TestCleaner:
    def test_the_contract_is_fully_populated(self):
        cleaned = TopJobsLkCleaner().clean_job(_raw())
        assert cleaned.job_title == "Call Center Executive"
        assert cleaned.company_name == "Micronet Global Services (Pvt) Ltd"
        assert cleaned.location_cleaned.startswith("Battaramulla")
        assert cleaned.posting_date == datetime(2026, 11, 20)
        assert cleaned.closing_date == datetime(2026, 11, 27)
        assert cleaned.currency_iso_code == "LKR"
        assert cleaned.pay_period == "monthly"
        assert cleaned.employment_type_code == "full_time"
        assert cleaned.remote_work_type_code == "on_site"

    def test_no_salary_is_invented(self):
        cleaned = TopJobsLkCleaner().clean_job(_raw())
        assert cleaned.salary_min is None and cleaned.salary_max is None
        assert cleaned.salary_disclosed is False
        assert cleaned.raw_payload["salary_published"] is False

    def test_an_image_only_ad_has_no_description_but_is_still_stored(self):
        cleaned = TopJobsLkCleaner().clean_job(_raw(description=None, description_is_image=True))
        assert cleaned.description_clean is None
        assert cleaned.word_count == 0
        assert cleaned.raw_payload["description_is_image"] is True
        assert cleaned.job_title

    def test_a_locationless_ad_falls_back_to_the_country(self):
        cleaned = TopJobsLkCleaner().clean_job(_raw(location=None))
        assert cleaned.location_cleaned == "Sri Lanka"

    def test_an_unknown_employer_is_not_an_empty_string(self):
        cleaned = TopJobsLkCleaner().clean_job(_raw(company_name=""))
        assert cleaned.company_name == "Unknown employer"

    def test_the_listing_teaser_is_not_used_as_the_description(self):
        cleaned = TopJobsLkCleaner().clean_job(_raw(description=None))
        assert cleaned.description_clean is None
        assert cleaned.raw_payload["listing_snippet"] == "Urgent"

    def test_quality_score_rewards_a_readable_ad(self):
        with_text = TopJobsLkCleaner().clean_job(_raw(description="x " * 250))
        without = TopJobsLkCleaner().clean_job(_raw(description=None))
        assert with_text.data_quality_score > without.data_quality_score

    def test_headcount_and_labels_survive_in_the_payload(self):
        cleaned = TopJobsLkCleaner().clean_job(_raw())
        assert cleaned.raw_payload["headcount"] == 20
        assert cleaned.raw_payload["ad_status_labels"] == ["Full Time", "Permanent", "Onsite"]

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Full Time", "full_time"),
            ("Part Time", "part_time"),
            ("Contract", "contract"),
            ("Temporary", "temporary"),
            ("Internship", "internship"),
            ("Freelance", "freelance"),
            ("Permanent", "full_time"),
            ("", None),
            (None, None),
        ],
    )
    def test_employment_type_mapping(self, value, expected):
        assert map_employment_type(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Onsite", "on_site"),
            ("On-site", "on_site"),
            ("Hybrid", "hybrid"),
            ("Remote", None),
            ("Work from Home", None),
            (None, None),
        ],
    )
    def test_work_mode_mapping(self, value, expected):
        assert map_work_mode(value) == expected


class TestClosingDateGuard:
    def test_a_deadline_after_the_posting_is_kept(self):
        assert storable_closing_date(date(2026, 11, 20), date(2026, 11, 27)) == datetime(
            2026, 11, 27
        )

    def test_a_deadline_before_the_posting_is_dropped(self):
        assert storable_closing_date(date(2026, 11, 20), date(2026, 11, 1)) is None

    def test_no_deadline_stays_none(self):
        assert storable_closing_date(date(2026, 11, 20), None) is None

    def test_the_cleaner_applies_the_guard(self):
        cleaned = TopJobsLkCleaner().clean_job(
            _raw(posted_date=date(2026, 11, 20), closing_date=date(2026, 11, 1))
        )
        assert cleaned.posting_date == datetime(2026, 11, 20)
        assert cleaned.closing_date is None


class TestValidator:
    def _jobs(self, n: int) -> list[RawTopJobsLkJob]:
        return [_raw(source_job_id=f"{i:010d}") for i in range(n)]

    def test_a_normal_batch_passes(self):
        jobs = self._jobs(60)
        report = TopJobsLkBatchValidator().validate(jobs, jobs)
        assert report.passed, report.issues

    def test_a_suspiciously_small_batch_fails(self):
        jobs = self._jobs(10)
        report = TopJobsLkBatchValidator().validate(jobs, jobs)
        assert not report.passed
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_duplicate_job_codes_are_flagged(self):
        jobs = self._jobs(60)
        jobs.append(jobs[0])
        report = TopJobsLkBatchValidator().validate(jobs, jobs)
        assert report.duplicate_source_job_ids

    def test_image_only_ads_do_not_fail_the_batch(self):
        jobs = [
            _raw(source_job_id=f"{i:010d}", description=None, description_is_image=True)
            for i in range(60)
        ]
        report = TopJobsLkBatchValidator().validate(jobs, jobs)
        assert report.passed, "a board of image-only ads is a property of the board"
        assert report.missing_field_rates["description"] == 1.0

    def test_thresholds_are_configurable(self):
        jobs = self._jobs(10)
        validator = TopJobsLkBatchValidator(TopJobsLkValidationSettings(min_expected_jobs=5))
        assert validator.validate(jobs, jobs).passed
