"""Unit tests for the JobSearch.az scraper (Azerbaijan).

Pinned measured facts (2026-10-18), read off a live Playwright render:

  * The first ``<h1>`` on the page is ``h1.company__title`` -- the EMPLOYER.
    The job title is ``h1.vacancy__title``, which renders *below* it.
  * ``#content_block`` is the description: 2,488 chars. Whole-page text is
    5,849 chars, so scraping ``body`` puts the filter sidebar in every row.
  * The deadline is Azerbaijani: "Son tarix 17 noy 2026".
  * The posting date is ONLY on the listing card and carries no year:
    "Bu gün" / "Dünən" / "16 okt".
  * The card's ``li.money`` is present but always empty -- there is no salary.

None of these tests touch the network: the fixtures below are the markup the
renderer produced, and every helper that needs a date takes ``today`` as an
argument so the assertions do not rot with the calendar.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from job_market_intel.cleaning.jobsearch_az_cleaner import (
    JobSearchAzCleaner,
    storable_closing_date,
)
from job_market_intel.scrapers.jobsearch_az.client import _slug_from_href
from job_market_intel.scrapers.jobsearch_az.config import JobSearchAzSettings
from job_market_intel.scrapers.jobsearch_az.exceptions import (
    JobSearchAzParseError,
    JobSearchAzResponseError,
)
from job_market_intel.scrapers.jobsearch_az.parser import (
    JobSearchAzParser,
    parse_deadline,
    parse_posted_label,
)

TODAY = date(2026, 10, 18)

#: A trimmed but structurally faithful copy of the rendered detail page.
#: Document order is preserved from the live render and matters:
#:   1. the related-jobs block sits in the LEFT column, so it comes FIRST. Its
#:      cards really do use ``h3.list__item__title``, but the deadline decoy
#:      below is deliberately over-specified -- on the measured page a related
#:      card cannot currently shadow ``.vacancy__deadline``. Scoping the
#:      selector to ``.vacancy__info`` costs nothing and means the class does
#:      not have to be re-checked every time the site ships a template change.
#:   2. then the company block, whose ``<h1>`` is the EMPLOYER.
#:   3. then this posting's own block, whose ``<h1>`` is the job title.
DETAIL = """<!DOCTYPE html><html><head>
<title>Resepşionist / Receptionist (Stomatoloji Klinika) - German Dental Clinic
 | JobSearch.az</title>
</head><body>
<nav><a href="/vacancies">Elanlar</a><a href="/categories">Kateqoriyalar</a></nav>
<div class="similar-vacancies">
  <h3 class="list__item__title">Daxili Nəzarət İdarəsinin Əməliyyatların icrasına
  nəzarət şöbəsinin kiçik mütəxəssisi/ mütəxəssis</h3>
  <span class="vacancy__deadline">Son tarix 3 noy 2026</span>
</div>
<div class="company">
  <div class="company__body"><div class="company__body__text">
    <h1 class="company__title">German Dental Clinic</h1>
    <div class="company__industry"><a href="#">İnsan sağlamlığı və sosial xidmətlər</a></div>
  </div></div>
</div>
<div class="vacancy">
  <div class="vacancy__header"><div class="vacancy__start">German Dental Clinic</div>
    <div class="list__item__end"><ul><li class="money"></li><li>1K</li></ul></div>
  </div>
  <div class="vacancy__info">
    <h1 class="vacancy__title">Resepşionist / Receptionist (Stomatoloji Klinika)</h1>
    <span class="vacancy__deadline">Son tarix 17 noy 2026</span>
    <span class="company__industry"><a href="#">Biznes, İdarəetmə və İnsan Resursları</a></span>
  </div>
  <div class="tab-content"><div id="content_block" class="content"><div class="content-text">
    <p><strong>Resepşionist vəzifəsi</strong></p>
    <p>German Dental Clinic Baku komandasına yüksək ünsiyyət bacarıqlarına malik,
       məsuliyyətli və peşəkar resepsionist axtarırıq.</p>
    <p>Xidmətçi vəzifələri:</p>
    <ul><li>Telefon qəbulu və qeydiyyat prosesinin idarə edilməsi;</li>
        <li>Müştəri sorğularının cavablandırılması və yönləndirilməsi;</li>
        <li>Təqvim və e-poçt cavablarının idarə olunması.</li></ul>
    <p>İş tələbləri:</p>
    <ul><li>Ən azı 2 il təcrübə;</li><li>İngilis dili bilikləri;</li>
        <li>Komanda işində təcrübə.</li></ul>
    <p>İş şərtləri: tam iş vaxtı, 5/2 iş rejimi.</p>
    <p>Bərabər haqqında danışılacaq.</p>
  </div></div></div>
</div>
</body></html>"""

#: What happens when only the listing card survived and the detail render failed.
CARD_ONLY = """<html><head><title>JobSearch.az</title></head>
<body><div id="__nuxt"></div></body></html>"""

#: A detail page whose description node arrived but whose class hooks did not.
#: The listing card still supplies the title, the employer and the date.
CARD_ONLY_WITH_HINTS = """<html><head><title>JobSearch.az</title></head>
<body><div id="content_block">Bir Operator axtarilir.</div></body></html>"""

PARSE = JobSearchAzParser()


def _detail(**overrides):
    kwargs = {
        "url": "https://jobsearch.az/vacancies/german-dental-clinic-x-154104",
        "listing_page": 1,
        "hints": {"date_label": "Bu gün"},
        "today": TODAY,
    }
    kwargs.update(overrides)
    return PARSE.parse("german-dental-clinic-x-154104", DETAIL, **kwargs)


class TestSelectors:
    def test_title_is_the_vacancy_h1_not_the_first_h1(self):
        """The company block renders FIRST, so a bare soup.h1 is the employer."""
        job = _detail()
        assert job.title == "Resepşionist / Receptionist (Stomatoloji Klinika)"
        assert job.company_name == "German Dental Clinic"

    def test_first_h1_in_the_document_is_the_employer(self):
        """Guard against someone 'simplifying' this back to soup.h1."""
        from bs4 import BeautifulSoup

        first_h1 = BeautifulSoup(DETAIL, "html.parser").h1
        assert first_h1.get_text(strip=True) == "German Dental Clinic"

    def test_description_is_scoped_to_content_block(self):
        """The whole-page text is navigation chrome; only #content_block is the ad."""
        from bs4 import BeautifulSoup

        job = _detail()
        whole_page = BeautifulSoup(DETAIL, "html.parser").get_text(" ", strip=True)
        assert job.description is not None
        assert len(whole_page) > len(job.description)
        # Chrome that must NOT survive into the description.
        assert "Kateqoriyalar" not in job.description
        assert "similar" not in job.description.lower()
        assert "Daxili Nəzarət" not in job.description
        # Real content that must.
        assert "İş tələbləri" in job.description
        assert "Komanda işində təcrübə" in job.description

    def test_category_and_employer_sector_are_distinct(self):
        job = _detail()
        assert job.industry == "Biznes, İdarəetmə və İnsan Resursları"
        assert job.employer_industry == "İnsan sağlamlığı və sosial xidmətlər"

    def test_similar_vacancies_are_not_stored_as_the_description(self):
        job = _detail()
        assert "nəzarət şöbəsinin" not in (job.description or "")

    def test_deadline_is_this_postings_not_the_carousels(self):
        """The related-jobs block carries its own .vacancy__deadline.

        ``select_one`` on the whole page would happily take the *first* one, so
        the parser has to reach inside the posting's own ``.vacancy__info``.
        This posting's deadline is 17 Nov; the carousel's is 3 Nov.
        """
        job = _detail()
        assert job.closing_date == date(2026, 11, 17)
        assert "3 noy" in DETAIL  # the decoy is really in the fixture


class TestDeadline:
    def test_azeri_deadline(self):
        assert parse_deadline("Son tarix 17 noy 2026") == date(2026, 11, 17)

    def test_long_month_name(self):
        assert parse_deadline("Son tarix: 3 noyabr 2026") == date(2026, 11, 3)

    def test_unparseable_deadline_is_none_not_today(self):
        assert parse_deadline("Son tarix yaxın günlərdə") is None
        assert parse_deadline(None) is None

    def test_unknown_month_is_none_not_today(self):
        """A deadline the parser cannot read must not become 'today'."""
        assert parse_deadline("Son tarix 16 xyz 2026") is None

    def test_impossible_day_is_none_not_today(self):
        assert parse_deadline("Son tarix 31 noy 2026") is None


class TestPostedLabel:
    def test_relative_today(self):
        assert parse_posted_label("Bu gün", TODAY) == TODAY

    def test_relative_yesterday(self):
        assert parse_posted_label("Dünən", TODAY) == date(2026, 10, 17)

    def test_relative_days_ago(self):
        assert parse_posted_label("3 gün əvvəl", TODAY) == date(2026, 10, 15)

    def test_year_less_day_month_takes_this_year(self):
        assert parse_posted_label("16 okt", TODAY) == date(2026, 10, 16)

    def test_year_less_day_month_rolls_back_when_it_would_be_future(self):
        """Read in January, '16 okt' means LAST October, not eight months out."""
        assert parse_posted_label("16 okt", date(2027, 1, 5)) == date(2026, 10, 16)

    def test_unknown_label_is_none_rather_than_guessed(self):
        for label in ("NaN", "", None, "keçən il", "16 zzz"):
            assert parse_posted_label(label, TODAY) is None

    def test_posted_date_reaches_the_model(self):
        assert _detail().posted_date == TODAY


class TestSlugExtraction:
    @pytest.mark.parametrize(
        ("href", "expected"),
        [
            ("/vacancies/amper-elektrik-surucu-150511", "amper-elektrik-surucu-150511"),
            ("/vacancies/x-154104/", "x-154104"),
            ("/vacancies/x-154104?ref=list", "x-154104"),
            ("/vacancies/x-154104/about-company", None),
            ("/vacancies/undefined", None),
            ("/vacancies/", None),
            ("/categories", None),
            (None, None),
        ],
    )
    def test_slugs(self, href, expected):
        assert _slug_from_href(href) == expected

    def test_sub_tabs_are_not_postings(self):
        """/vacancies/<slug>/vacancies is the "other jobs" tab, not a posting."""
        assert _slug_from_href("/vacancies/amper-elektrik-surucu-150511/vacancies") is None


class TestParserFailures:
    def test_detail_without_a_title_raises(self):
        with pytest.raises(JobSearchAzParseError, match="vacancy__title"):
            PARSE.parse("slug-1", CARD_ONLY, hints={"title": None, "company": None})

    def test_missing_html_is_not_silently_stored(self):
        """A card with no description is not a posting; storing it would be noise."""
        with pytest.raises(JobSearchAzParseError, match="no rendered HTML"):
            PARSE.parse("slug-1", None, hints={"title": "T", "company": "C"})

    def test_half_rendered_page_is_dropped_not_stored_empty(self):
        """The header and the description arrive from two different requests.

        Four of thirty postings measured this way landed with
        description_clean = NULL before the client started waiting on
        #content_block. An empty description is a worse row than no row.
        """
        half = """<html><body><div class="company">
            <h1 class="company__title">IRES</h1></div>
          <div class="vacancy__info">
            <h1 class="vacancy__title">Internal Control Expert</h1>
            <span class="vacancy__deadline">Son tarix 12 noy 2026</span>
          </div></body></html>"""
        with pytest.raises(JobSearchAzParseError, match="half-loaded page"):
            PARSE.parse("half-1", half, hints={"date_label": "Bu gün"}, today=TODAY)

    def test_card_hints_rescue_a_detail_page_whose_hooks_did_not_match(self):
        job = PARSE.parse(
            "slug-1",
            CARD_ONLY_WITH_HINTS,
            hints={"title": "1C Operator", "company": "FBC MMC", "date_label": "Dünən"},
            today=TODAY,
        )
        assert job.title == "1C Operator"
        assert job.company_name == "FBC MMC"
        assert job.posted_date == date(2026, 10, 17)
        assert job.description == "Bir Operator axtarilir."

    def test_parse_many_reports_every_failure(self):
        parsed, issues = PARSE.parse_many(
            [
                {"job_id": "ok-1", "html": DETAIL, "hints": {"date_label": "Bu gün"}},
                {"job_id": "broken-1", "html": None},
                {"job_id": "broken-2", "html": CARD_ONLY, "hints": {}},
            ]
        )
        assert len(parsed) == 1
        assert len(issues) == 2
        assert any("broken-1" in i for i in issues)
        assert any("broken-2" in i for i in issues)


class TestCleaner:
    def test_no_salary_is_invented(self):
        """The card's li.money is empty; a salary must not appear out of nowhere."""
        cleaned = JobSearchAzCleaner().clean_job(_detail())
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_pay_period_is_a_valid_schema_value(self):
        cleaned = JobSearchAzCleaner().clean_job(_detail())
        assert cleaned.pay_period in {"hourly", "daily", "weekly", "monthly", "yearly"}
        assert cleaned.currency_iso_code == "AZN"

    def test_word_count_tracks_the_scoped_description(self):
        cleaned = JobSearchAzCleaner().clean_job(_detail())
        assert cleaned.description_clean is not None
        assert cleaned.word_count == len(cleaned.description_clean.split())
        assert "Kateqoriyalar" not in cleaned.description_clean

    def test_location_is_country_only_not_a_guessed_city(self):
        """The detail page names Baku in prose only; inventing it would be wrong."""
        cleaned = JobSearchAzCleaner().clean_job(_detail())
        assert cleaned.location_cleaned == "Azerbaijan"

    def test_employer_sector_is_kept_in_the_raw_payload(self):
        cleaned = JobSearchAzCleaner().clean_job(_detail())
        assert cleaned.raw_payload["employer_industry"] == "İnsan sağlamlığı və sosial xidmətlər"
        assert cleaned.raw_payload["language"] == "az"


class TestClosingDateGuard:
    def test_deadline_before_posting_is_dropped(self):
        """Year-less labels can invert the pair; the CHECK constraint would abort."""
        assert storable_closing_date(date(2026, 10, 18), date(2026, 10, 1)) is None

    def test_deadline_after_posting_is_kept(self):
        assert storable_closing_date(date(2026, 10, 18), date(2026, 11, 17)) == date(2026, 11, 17)

    def test_same_day_is_kept(self):
        assert storable_closing_date(date(2026, 10, 18), date(2026, 10, 18)) == date(2026, 10, 18)

    def test_no_posting_date_keeps_the_deadline(self):
        assert storable_closing_date(None, date(2026, 11, 17)) == date(2026, 11, 17)

    def test_cleaner_applies_the_guard(self):
        job = _detail(hints={"date_label": "16 okt"})  # -> 2026-10-16, deadline 2026-11-17
        assert job.closing_date == date(2026, 11, 17)
        cleaned = JobSearchAzCleaner().clean_job(job)
        assert cleaned.closing_date == datetime(2026, 11, 17)
        assert cleaned.posting_date == datetime(2026, 10, 16)


class TestClientContract:
    def test_listing_url(self):
        assert JobSearchAzSettings().base_url == "https://jobsearch.az"
        from job_market_intel.scrapers.jobsearch_az.client import JobSearchAzClient

        assert (
            JobSearchAzClient(JobSearchAzSettings()).listing_url()
            == "https://jobsearch.az/vacancies"
        )

    def test_empty_discovery_raises_rather_than_returning_nothing(self):
        """A silently empty result is the failure mode this project keeps hitting."""
        from job_market_intel.scrapers.jobsearch_az.client import JobSearchAzClient

        client = JobSearchAzClient(JobSearchAzSettings())
        client.fetch_listing_page = lambda page=1: {}
        with pytest.raises(JobSearchAzResponseError, match="markup changed"):
            client.discover_detail_paths()

    def test_render_failure_is_reported_not_swallowed(self):
        from job_market_intel.scrapers.jobsearch_az.client import JobSearchAzClient
        from job_market_intel.scrapers.jobsearch_az.exceptions import JobSearchAzFetchError

        client = JobSearchAzClient(JobSearchAzSettings())

        def boom(page=1):
            raise JobSearchAzFetchError("chromium missing")

        client.fetch_listing_page = boom
        found, failures = client.discover_detail_paths()
        assert found == {}
        assert "page=1" in failures


class TestFetchRawJobs:
    """The browser is never touched here; ``_render_many`` is stubbed out."""

    def _client(self, **overrides):
        from job_market_intel.scrapers.jobsearch_az.client import JobSearchAzClient

        settings = JobSearchAzSettings(**overrides)
        client = JobSearchAzClient(settings)
        client.discover_detail_paths = lambda: (
            {
                f"slug-{i}": {
                    "path": f"/vacancies/slug-{i}",
                    "title": f"Job {i}",
                    "company": "Acme",
                    "date_label": "Bu gün",
                    "page": 1,
                }
                for i in range(1, 6)
            },
            {},
        )
        return client

    def test_budget_is_respected(self):
        client = self._client(max_jobs_per_run=3)
        client._render_many = lambda urls: ({u: DETAIL for u in urls}, {})
        records, failures = client.fetch_raw_jobs()
        assert len(records) == 3
        assert failures == {}

    def test_one_browser_for_the_whole_batch(self):
        """30 postings must not mean 30 Chromium launches."""
        client = self._client(max_jobs_per_run=5)
        calls: list[list[str]] = []

        def render(urls):
            calls.append(list(urls))
            return {u: DETAIL for u in urls}, {}

        client._render_many = render
        client.fetch_raw_jobs()
        assert len(calls) == 1
        assert len(calls[0]) == 5

    def test_a_missing_browser_is_recorded_not_hidden(self):
        """Otherwise every record parses to nothing and the run still exits 0."""
        from job_market_intel.scrapers.jobsearch_az.exceptions import JobSearchAzFetchError

        client = self._client(max_jobs_per_run=2)

        def boom(urls):
            raise JobSearchAzFetchError("could not launch Chromium")

        client._render_many = boom
        records, failures = client.fetch_raw_jobs()
        assert "browser" in failures
        assert len(records) == 2
        assert all(r["html"] is None for r in records)
        parsed, issues = PARSE.parse_many(records)
        assert parsed == []
        assert len(issues) == 2

    def test_a_page_that_never_produced_a_description_is_named(self):
        """``_render_many`` reports failures keyed by URL; they must reach the
        caller keyed by slug, or the run's failure count is a row-count
        discrepancy nobody can act on."""
        client = self._client(max_jobs_per_run=3)
        client._render_many = lambda urls: (
            {urls[0]: DETAIL},
            {urls[1]: "TimeoutError: #content_block not attached", urls[2]: "TimeoutError: x"},
        )
        records, failures = client.fetch_raw_jobs()
        assert set(failures) == {"slug-2", "slug-3"}
        assert failures["slug-2"].startswith("TimeoutError")
        parsed, issues = PARSE.parse_many(records)
        assert len(parsed) == 1
        assert len(issues) == 2
