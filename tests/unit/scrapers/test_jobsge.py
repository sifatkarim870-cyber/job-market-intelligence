"""Unit tests for the Jobs.ge scraper (Georgia).

Pinned measured facts (2026-10-18, off live Playwright renders):

  * The **English detail page is a stub**: title, employer, one sentence, then
    "See full text of this announcement in Georgian." -- 548 characters for the
    posting whose Georgian page is 4,421.
  * The ad id is a **query parameter**: ``/en/?view=jobs&id=761321``.
  * The listing is a **plain HTML table**, header
    ``* | VIP Advertisements | | Provided By | Published | Deadline``.
  * Dates are **Georgian month names with no year**, on one line:
    ``გამოქვეყნდა: 16 ოქტომბერი / ბოლო ვადა: 16 ნოემბერი``.
  * Pagination is ``?page=N``; page 1 had 308 ads, page 2 added 300 with no
    overlap.
  * **No salary field and no location field** -- pay is prose mixed with
    internship rates, Tbilisi is inside the body text.

No test touches the network. ``today`` is injected so the date assertions do
not rot with the calendar.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from job_market_intel.cleaning.jobsge_cleaner import (
    JobsGeCleaner,
    clean_editor_text,
    map_employment_type,
    storable_closing_date,
)
from job_market_intel.scrapers.jobsge.client import JobsGeClient
from job_market_intel.scrapers.jobsge.config import JobsGeSettings
from job_market_intel.scrapers.jobsge.exceptions import (
    JobsGeParseError,
    JobsGeResponseError,
)
from job_market_intel.scrapers.jobsge.parser import (
    JobsGeParser,
    parse_detail,
    parse_english_date,
    parse_georgian_date,
    parse_listing,
    split_published_deadline,
)

TODAY = date(2026, 10, 18)
AD_ID = "761321"

#: The English stub, verbatim in shape. A parser that reads this for the
#: description stores 548 characters of boilerplate and calls it a job ad.
STUB_EN = """<!DOCTYPE html><html><body>
<table><tr><td>All Jobs
All Ads by this Client
Printer Friendly
Ad title: Senior IT Support/System Administrator
Provided By: Geosoft Cloud
Published: 16 October / Deadline: 16 November
Geosoft Cloud is pleased to announce an opening for the position of Title.

See full text of this announcement in Georgian.
</td></tr>
<tr><td>All Jobs</td></tr>
<tr><td>All Ads by this Client</td></tr>
<tr><td>Printer Friendly</td></tr></table>
</body></html>"""

#: The Georgian page: labelled rows, then the ad body.
#: The live page nests tables, so BeautifulSoup's ``find_all("tr")`` returns an
#: OUTER row whose single cell holds the entire page -- nav chrome, the labelled
#: rows and the ad body all concatenated -- and that outer row is the LONGEST
#: thing on the page. Measured 2026-10-19 on ad 761321, row lengths:
#: ``[4140, 65, 57, 26, 50, 3872, 65, 17]``. The ad body is row 5 at 3,872
#: chars; the 4,140-char blob is row 0.
#:
#: So "take the longest row" on its own is the wrong rule -- it would store the
#: blob, description complete with "დასახელება:" and "გამოქვეყნდა:" glued to its
#: front. What actually keeps the blob out is the chrome guard: row 0 starts
#: with "ყველა ვაკანსია". Both rows are reproduced here so the guard is under
#: test rather than accidentally correct.
#: The blob row, kept as its own constant because it is one table cell and
#: therefore one very long line by construction.
_OUTER_BLOB = (
    "ყველა ვაკანსია ამოსაბეჭდი ვერსია "
    "დასახელება: OUTER BLOB TITLE "
    "მომწოდემელი: Geosoft Cloud "
    "გამოქვეყნდა: 16 ოქტომბერი / ბოლო ვადა: 16 ნოემბერი "
    "OUTER BLOB BODY Google Cloud Synology "
    "ხელფასი: 3400 ლარიდან და მისი ოდენობა შეზღუდული არ არის არაფრით."
)

DETAIL_GE = f"""<!DOCTYPE html><html><body>
<table><tr><td>
<table><tr><td>{_OUTER_BLOB}</td></tr>
<tr><td>ყველა ვაკანსია	ამ ორგანიზაციის ყველა განცხადება
ამოსაბეჭდი ვერსია</td></tr>
<tr><td>დასახელება: უფროსი IT მხარდაჭერის/სისტემის ადმინისტრატორი</td></tr>
<tr><td>მომწოდემელი: Geosoft Cloud</td></tr>
<tr><td>ყველა ვაკანსია	ამ ორგანიზაციის ყველა განცხადება
ამოსაბეჭდი ვერსია</td></tr>
<tr><td>დასახელება: უფროსი IT მხარდაჭერის/სისტემის ადმინისტრატორი</td></tr>
<tr><td>მომწოდებელი: Geosoft Cloud</td></tr>
<tr><td>გამოქვეყნდა: 16 ოქტომბერი / ბოლო ვადა: 16 ნოემბერი</td></tr>
<tr><td>Senior IT Support/System Administrator (Google Workspace &amp; Cloud Track)

"Geosoft Cloud"-ის შესახებ:
"Geosoft Cloud" არის Google Cloud-ის, AWS-ის, Microsoft-ისა და
Synology-ის პარტნიორი კომპანია რეგიონში.

როლი:
ვეძებთ გამოცდილ Senior IT Support ან System Administrator სპეციალისტს
მინიმუმ 3-წლიანი პრაქტიკული გამოცდილებით.

** სამუშაო ადგილას მისვლა;
** მონიტორინგის დაყოფნა;

ხელფასი: 3400 ლარიდან და მისი ოდენობა შეზღუდული არ არის არაფრით.</td></tr>
<tr><td>ყველა ვაკანსია	ამოსაბეჭდი ვერსია</td></tr>
<tr><td>ბმულის გადაგზავნა</td></tr>
</table></td></tr></table></body></html>"""

#: The listing table, header row included.
LISTING = """<!DOCTYPE html><html><body><table><tbody>
<tr><th style="padding:0px 12px;"></th><th style="width:50%">VIP Advertisements</th>
<th style="width:16px">&nbsp;</th><th style="width:30%">Provided By</th>
<th style="width:10%">Published</th><th style="width:10%">Deadline</th></tr>
<tr><td><img id="761321" src="/i/unstar.gif"></td>
<td><a href="/en/?view=jobs&amp;id=761321" class="vip">Senior IT Support/System Administrator</a>
<a href="/en/?view=jobs&amp;id=761321" target="_blank"><img src="/i/newwindow.gif"></a></td>
<td>Geosoft Cloud</td><td>16 October</td><td>16 November</td></tr>
<tr><td><img id="761244" src="/i/unstar.gif"></td>
<td><a href="/en/?view=jobs&amp;id=761244" class="vip">Restaurant Supervisor</a></td>
<td>Entrée</td><td>16 October</td><td>16 November</td></tr>
<tr><td><a href="/ge/ads/" class="vip">Post an ad</a></td><td>Paid service</td></tr>
</tbody></table></body></html>"""

PARSE = JobsGeParser()


def _detail(html: str = DETAIL_GE, ad_id: str = AD_ID, **hints):
    kwargs = {
        "url": f"https://jobs.ge/ge/?view=jobs&id={ad_id}",
        "listing_page": 1,
        "hints": hints
        or {
            "title_en": "Senior IT Support/System Administrator",
            "company": "Geosoft Cloud",
            "published": "16 October",
            "deadline": "16 November",
        },
        "today": TODAY,
    }
    return parse_detail(ad_id, html, **kwargs)


class TestListingTable:
    def test_ids_and_english_titles_come_out(self):
        cards = parse_listing(LISTING, 1)
        assert set(cards) == {"761321", "761244"}, "the 'Post an ad' row is not a posting"
        assert cards["761321"]["title_en"] == "Senior IT Support/System Administrator"
        assert cards["761244"]["title_en"] == "Restaurant Supervisor"

    def test_company_and_dates_come_out(self):
        card = parse_listing(LISTING, 1)["761244"]
        assert card["company"] == "Entrée"
        assert card["published"] == "16 October"
        assert card["deadline"] == "16 November"

    def test_a_non_posting_anchor_is_not_discovered(self):
        """/ge/ads/ has an <a class="vip"> but no ?id=, so it is not an ad."""
        assert "ads" not in parse_listing(LISTING, 1)

    def test_an_empty_table_yields_nothing_rather_than_inventing_ads(self):
        assert parse_listing("<html><body><table></table></body></html>") == {}

    def test_the_header_row_is_not_read_as_a_posting(self):
        """It is all <th>, and carries no ?id= anchor."""
        cards = parse_listing(LISTING, 1)
        assert all(
            not c["title_en"] or "Advertisements" not in c["title_en"] for c in cards.values()
        )


class TestTwoLanguages:
    def test_the_english_page_has_no_description(self):
        """548 characters ending in 'See full text ... in Georgian.'"""
        with pytest.raises(JobsGeParseError, match="დასახელება"):
            _detail(STUB_EN)

    def test_the_georgian_page_does(self):
        job = _detail()
        assert job.title == "უფროსი IT მხარდაჭერის/სისტემის ადმინისტრატორი"
        assert job.company_name == "Geosoft Cloud"
        # The trimmed fixture is 438 chars; the live page is 4,421 and the
        # English stub is 548. What matters is that it is the ad body, not the
        # boilerplate, which the assertions below pin down.
        assert job.description is not None and len(job.description) > 300

    def test_the_english_title_is_kept_separately_not_substituted(self):
        job = _detail()
        assert job.title_en == "Senior IT Support/System Administrator"
        assert job.title != job.title_en

    def test_the_description_excludes_the_chrome_rows(self):
        job = _detail()
        assert "ბმულის გადაგზავნა" not in job.description, "'Forward Link' row leaked"
        assert "ამოსაბეჭდი ვერსია" not in job.description
        assert "ყველა ვაკანსია" not in job.description
        assert "გამოქვეყნდა:" not in job.description, "a labelled row leaked"

    def test_the_description_keeps_the_real_body(self):
        job = _detail()
        assert "Google Cloud" in job.description
        assert "ხელფასი" in job.description

    def test_the_outer_blob_row_never_becomes_the_description(self):
        """The longest row on the page, and the wrong one.

        Measured on ad 761321: row 0 is a 4,140-character single cell holding
        nav chrome, the labelled rows AND the ad body, because the live page
        nests its tables. A "longest row wins" rule with no chrome guard stores
        that blob -- a description beginning "ყველა ვაკანსია დასახელება: ...".
        """
        job = _detail()
        assert "OUTER BLOB" not in job.description, "the nested-table blob won"
        assert "OUTER BLOB BODY" not in job.description

    def test_a_short_non_chrome_decoy_does_not_beat_the_ad_body(self):
        """'პროფესია: სრული დღე' is inside the blob; the body still has to win."""
        job = _detail()
        assert job.description.startswith("Senior IT Support")


class TestListingDecoys:
    """Rows that look like postings in the listing table and are not."""

    #: A row with four cells -- so it clears the cell-count guard -- whose only
    #: anchor is "/ge/ads/", i.e. the "Post an ad" call to action.
    DECOY = (
        '<tr><td><a href="/ge/ads/" class="vip">Post an ad</a></td>'
        "<td>Paid service</td><td>Geosoft Cloud</td><td>16 October</td></tr>"
    )

    def test_a_four_cell_row_with_a_non_ad_anchor_is_not_a_posting(self):
        html = LISTING.replace(
            '<tr><td><a href="/ge/ads/" class="vip">Post an ad</a></td><td>Paid service</td></tr>',
            self.DECOY,
        )
        cards = parse_listing(html, 1)
        assert set(cards) == {"761321", "761244"}
        assert not any("Post an ad" in (c["title_en"] or "") for c in cards.values())

    def test_published_and_deadline_are_not_reversed(self):
        """Both columns read '16 October' / '16 November' -- swap-proof by value."""
        cards = parse_listing(LISTING, 1)
        for card in cards.values():
            assert card["published"] == "16 October"
            assert card["deadline"] == "16 November", "published and deadline swapped"

    def test_the_detail_page_wins_over_the_listing_for_dates(self):
        """The detail page is authoritative; the listing is a hint."""
        html = DETAIL_GE.replace("16 ოქტომბერი", "9 იანვარი")
        job = _detail(html)
        assert job.posted_date == date(2026, 1, 9), "a stale listing hint overrode the page"
        assert job.closing_date == date(2026, 11, 16)


class TestDates:
    def test_published_and_deadline_split_apart(self):
        published, deadline = split_published_deadline(
            "გამოქვეყნდა: 16 ოქტომბერი / ბოლო ვადა: 16 ნოემბერი"
        )
        assert published == "16 ოქტომბერი"
        assert deadline == "16 ნოემბერი"

    def test_georgian_month_names(self):
        assert parse_georgian_date("16 ოქტომბერი", TODAY) == date(2026, 10, 16)
        assert parse_georgian_date("3 იანვარი", TODAY) == date(2026, 1, 3)
        assert parse_georgian_date("1 დეკემბერი", TODAY) == date(2025, 12, 1)

    def test_english_month_names_also_parse(self):
        """The listing's own columns are English, and are the fallback."""
        assert parse_english_date("16 October", TODAY) == date(2026, 10, 16)
        assert parse_georgian_date("16 October", TODAY) == date(2026, 10, 16)

    def test_a_year_less_date_rolls_back_rather_than_landing_in_the_future(self):
        """A *posting* date is anchored on today and rolled back if in the future."""
        assert parse_georgian_date("16 ნოემბერი", date(2026, 10, 20)) == date(2025, 11, 16)
        assert parse_english_date("16 November", date(2026, 10, 20)) == date(2025, 11, 16)
        assert parse_georgian_date("16 ნოემბერი", date(2026, 12, 1)) == date(2026, 11, 16)


class TestDeadlineIsAnchoredOnThePostingDateNotToday:
    """The bug the first live run exposed: 6 of 6 deadlines destroyed.

    A posting anchored on today and rolled *backwards* when it looks future is
    right for a posting date -- nobody publishes tomorrow. Applied to a
    deadline it is exactly wrong, because a deadline *is* meant to be in the
    future: read on 19 October, "16 November" resolved to 2026-11-16, was
    pushed back to 2025-11-16 as "in the future", and was then dropped by the
    closing-date guard. Every row in the run lost its deadline.
    """

    def test_a_future_deadline_is_not_rolled_back(self):
        posted = date(2026, 10, 16)
        assert parse_georgian_date("16 ნოემბერი", date(2026, 10, 19), reference=posted) == date(
            2026, 11, 16
        )

    def test_the_same_ad_read_in_december_still_resolves(self):
        """Ads linger after they expire; the answer must not move with the clock."""
        posted = date(2026, 10, 16)
        assert parse_georgian_date("16 ნოემბერი", date(2026, 12, 5), reference=posted) == date(
            2026, 11, 16
        )

    def test_a_deadline_before_the_posting_date_rolls_forward_a_year(self):
        """Posted 16 January, deadline reads '16 December' -> that December."""
        posted = date(2026, 1, 16)
        assert parse_georgian_date("16 დეკემბერი", date(2026, 1, 20), reference=posted) == date(
            2026, 12, 16
        )

    def test_the_roll_forward_reaches_the_next_calendar_year(self):
        """Posted 20 December, deadline reads '16 January' -> NEXT January.

        This is the only case that needs ``reference.year + 1``: the same month
        has already passed in the posting's own year, so the deadline is a full
        year out. Trying only ``reference.year`` here returns nothing.
        """
        posted = date(2026, 12, 20)
        assert parse_georgian_date("16 იანვარი", date(2026, 12, 21), reference=posted) == date(
            2027, 1, 16
        )
        assert parse_english_date("16 January", date(2026, 12, 21), reference=posted) == date(
            2027, 1, 16
        )

    def test_the_english_fallback_behaves_the_same(self):
        posted = date(2026, 10, 16)
        assert parse_english_date("16 November", date(2026, 10, 19), reference=posted) == date(
            2026, 11, 16
        )

    def test_the_parsed_model_keeps_the_deadline(self):
        job = _detail()
        assert job.posted_date == date(2026, 10, 16)
        assert job.closing_date == date(2026, 11, 16), "the November deadline was rolled back"

    def test_the_cleaner_keeps_the_deadline(self):
        cleaned = JobsGeCleaner().clean_job(_detail())
        assert cleaned.posting_date == datetime(2026, 10, 16)
        assert cleaned.closing_date == datetime(2026, 11, 16)

    @pytest.mark.parametrize("bad", ["", None, "TBD", "soon", "NaN", "31 თვის"])
    def test_unreadable_dates_are_none_not_today(self, bad):
        assert parse_georgian_date(bad, TODAY) is None

    def test_both_dates_reach_the_model(self):
        job = _detail()
        assert job.posted_date == date(2026, 10, 16)
        assert job.closing_date == date(2026, 11, 16)

    def test_the_english_listing_hints_fill_in_when_georgian_is_missing(self):
        html = DETAIL_GE.replace(
            "გამოქვეყნდა: 16 ოქტომბერი / ბოლო ვადა: 16 ნოემბერი",
            "გამოქვეყნდა: ? / ბოლო ვადა: ?",
        )
        job = _detail(html)
        assert job.posted_date == date(2026, 10, 16), "should fall back to the listing"
        assert job.closing_date == date(2026, 11, 16)


class TestWhatIsNotScraped:
    def test_no_salary_is_invented_from_the_prose(self):
        """'ხელფასი: 3400 ლარიდან' is in the body; it is never a field."""
        job = _detail()
        cleaned = JobsGeCleaner().clean_job(job)
        assert cleaned.salary_min is None and cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_no_city_is_invented_from_the_body_text(self):
        cleaned = JobsGeCleaner().clean_job(_detail())
        assert cleaned.location_cleaned == "Georgia"

    def test_country_is_pinned_to_georgia(self):
        assert _detail().country == "Georgia"


class TestCleaner:
    def test_editor_artifacts_are_stripped(self):
        assert clean_editor_text("** სამუშაო ადგილას მისვლა; ** დაყოფნა;") == (
            "სამუშაო ადგილას მისვლა; დაყოფნა;"
        )

    def test_description_keeps_the_georgian_body(self):
        cleaned = JobsGeCleaner().clean_job(_detail())
        assert cleaned.description_clean is not None
        assert "Google Cloud" in cleaned.description_clean
        assert "**" not in cleaned.description_clean
        assert cleaned.word_count == len(cleaned.description_clean.split())

    def test_english_title_is_kept_in_the_payload(self):
        cleaned = JobsGeCleaner().clean_job(_detail())
        assert cleaned.raw_payload["title_en"] == "Senior IT Support/System Administrator"
        assert cleaned.job_title == "უფროსი IT მხარდაჭერის/სისტემის ადმინისტრატორი"

    def test_the_english_title_lands_in_the_shared_contract(self):
        """It has to be a CleanedJob field, not just payload.

        raw_payload is NOT persisted -- measured on the first jobsge run:
        60 rows, `raw_html_ref` NULL on every one. Storing title_en only there
        loses it entirely.
        """
        cleaned = JobsGeCleaner().clean_job(_detail())
        assert cleaned.job_title_en == "Senior IT Support/System Administrator"
        assert cleaned.job_title_en != cleaned.job_title

    def test_no_english_title_yields_none_not_an_empty_string(self):
        job = _detail(hints={"title_en": None})
        assert JobsGeCleaner().clean_job(job).job_title_en is None

    def test_pay_period_is_a_valid_schema_value(self):
        cleaned = JobsGeCleaner().clean_job(_detail())
        assert cleaned.pay_period in {"hourly", "daily", "weekly", "monthly", "yearly"}
        assert cleaned.currency_iso_code == "GEL"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("FULL_TIME", "full_time"),
            ("PART_TIME", "part_time"),
            ("INTERN", "internship"),
            ("სრული დღე", None),
            ("", None),
            (None, None),
        ],
    )
    def test_employment_type_mapping(self, value, expected):
        assert map_employment_type(value) == expected


class TestClosingDateGuard:
    def test_deadline_before_posting_is_dropped(self):
        assert storable_closing_date(date(2026, 10, 16), date(2025, 11, 16)) is None

    def test_deadline_after_posting_is_kept(self):
        assert storable_closing_date(date(2026, 10, 16), date(2026, 11, 16)) == date(2026, 11, 16)

    def test_no_posting_date_keeps_the_deadline(self):
        assert storable_closing_date(None, date(2026, 11, 16)) == date(2026, 11, 16)

    def test_the_cleaner_applies_it(self):
        """The guard still bites when a genuinely inverted pair is built by hand."""
        job = _detail()
        job.posted_date = date(2026, 10, 16)
        job.closing_date = date(2026, 10, 1)
        cleaned = JobsGeCleaner().clean_job(job)
        assert cleaned.posting_date == datetime(2026, 10, 16)
        assert cleaned.closing_date is None, "a deadline before the posting must be dropped"


class TestClientContract:
    def test_listing_and_detail_use_different_languages(self):
        s = JobsGeSettings()
        assert s.listing_path == "/en/jobs"
        assert s.detail_lang == "ge", (
            "the English detail page is a 548-character stub with no description"
        )
        assert s.listing_lang == "en"

    def test_page_one_carries_no_page_param(self):
        client = JobsGeClient(JobsGeSettings())
        assert client.listing_url(1) == "https://jobs.ge/en/jobs"
        assert client.listing_url(2) == "https://jobs.ge/en/jobs?page=2"

    def test_the_id_is_a_query_parameter(self):
        client = JobsGeClient(JobsGeSettings())
        url = client.detail_url("761321")
        assert url.endswith("?view=jobs&id=761321")
        assert "/761321" not in url

    def test_empty_discovery_raises_rather_than_returning_nothing(self):
        client = JobsGeClient(JobsGeSettings())
        client.fetch_listing_page = lambda page=1: ("<html></html>", {})
        with pytest.raises(JobsGeResponseError, match="markup changed"):
            client.discover_detail_paths()

    def test_a_page_that_never_rendered_is_named(self):
        client = JobsGeClient(JobsGeSettings(max_jobs_per_run=3))
        client.discover_detail_paths = lambda: (
            {
                str(i): {
                    "title_en": f"Job {i}",
                    "company": "X",
                    "published": None,
                    "deadline": None,
                    "page": 1,
                }
                for i in (1, 2, 3)
            },
            {},
        )
        client._render_many = lambda ids: ({}, {i: "TimeoutError" for i in ids})
        records, failures = client.fetch_raw_jobs()
        assert set(failures) == {"1", "2", "3"}
        assert all(r["html"] is None for r in records)
        parsed, issues = PARSE.parse_many(records)
        assert parsed == [] and len(issues) == 3

    def test_hints_from_the_listing_reach_the_parser(self):
        client = JobsGeClient(JobsGeSettings(max_jobs_per_run=2))
        client.discover_detail_paths = lambda: (
            {
                "1": {
                    "title_en": "Chef",
                    "company": "Antre",
                    "published": "16 October",
                    "deadline": "16 November",
                    "page": 1,
                },
                "2": {
                    "title_en": "Driver",
                    "company": "Geosoft",
                    "published": None,
                    "deadline": None,
                    "page": 1,
                },
            },
            {},
        )
        client._render_many = lambda ids: ({i: DETAIL_GE for i in ids}, {})
        records, _ = client.fetch_raw_jobs()
        job = PARSE.parse(
            records[0]["job_id"], records[0]["html"], hints=records[0]["hints"], today=TODAY
        )
        assert job.title_en == "Chef"
        assert job.company_name == "Geosoft Cloud", "the detail page wins over the hint"
