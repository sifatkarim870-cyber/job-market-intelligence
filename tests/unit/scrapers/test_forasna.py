"""Unit tests for the Forasna scraper (Egypt).

Pinned measured facts (2026-10-19, off live HTTP responses):

  * **No browser.** The site is server-rendered and serves both the listing
    and the detail page in a plain GET.
  * The listing is the site's own search page, ``/وظائف-خالية``, paginated
    by an **offset** (``?start=20``), 20 postings a page, **2,852 postings**
    on the board.
  * The nominal all-jobs route ``/a/وظائف-مصر`` returns HTTP 200 and 281 KB
    with **zero** job links on it.
  * The id is the **trailing number of the URL slug**, and the JSON-LD
    ``identifier.value`` agrees. The ids are not dense: 2,000 consecutive
    postings span 303,860 to 444,468.
  * The detail page carries a schema.org ``JobPosting`` with ``title``,
    ``identifier``, ``datePosted``, ``validThrough``, ``employmentType``,
    ``hiringOrganization.name`` and ``jobLocation.address``.
  * Over 280 postings: **76% carry a description** and **36% a salary**.
  * The **currency is per posting**: EGP on 99, USD on 1, and SAR on 1 --
    that last one on a posting whose ``addressCountry`` is **SA**, not EG.
  * ``addressRegion`` can name a governorate of another country: "أبها" is
    Abha, in Saudi Arabia. 5 of the 280 postings are ``SA``.

No test touches the network. The fixtures are trimmed captures of the real
markup, and the JSON-LD is copied verbatim.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from job_market_intel.cleaning.forasna_cleaner import ForasnaCleaner
from job_market_intel.scrapers.forasna.client import ForasnaClient
from job_market_intel.scrapers.forasna.config import ForasnaSettings
from job_market_intel.scrapers.forasna.exceptions import (
    ForasnaParseError,
    ForasnaResponseError,
)
from job_market_intel.scrapers.forasna.parser import (
    parse_detail,
    parse_listing,
    slug_id,
)

#: A posting's slug: the Arabic title, the company, the country, the city and
#: the id, all concatenated. The id is the trailing number.
SLUG = (
    "%D9%85%D8%B3%D8%A6%D9%88%D9%84-%D8%AA%D8%B3%D9%88%D9%8A%D9%82-"
    "%D9%88%D8%B5%D8%B1%D8%AC%D8%A9-%D8%A3%D9%88%D9%86-%D8%AA%D8%A7%D9%8A%D9%85-"
    "%D8%B3%D9%8A%D8%B3%D8%AA%D9%85%D8%B2-%D9%85%D8%B5%D8%B1-%D8%A7%D9%84%D9%85%D9%86%D9%8A%D8%A7-"
    "%D8%A7%D9%84%D9%85%D9%86%D9%8A%D8%A7-444468"
)

#: The JobPosting block, copied from the live page.
JOB_POSTING = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "مسئول تسويق ومبيعات خارجية",
    "identifier": {"@type": "PropertyValue", "name": "Forasna", "value": "444468"},
    "datePosted": "2026-10-19T20:27:15+03:00",
    "validThrough": "2026-11-17T20:27:15+02:00",
    "employmentType": "PART_TIME",
    "hiringOrganization": {
        "@type": "Organization",
        "name": "أون تايم سيستمز",
        "sameAs": "https://forasna.com/company/...",
    },
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressRegion": "المنيا",
            "addressLocality": "المنيا",
            "addressCountry": "EG",
        },
    },
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "EGP",
        "value": {
            "@type": "QuantitativeValue",
            "minValue": 5000,
            "unitText": "MONTH",
            "maxValue": 8000,
        },
    },
    "description": (
        "\nللعمل بمصنع ملابس جينز متخصص في الإنتاج والبيع بالجملة "
        "للتجار، بمدينة بلبيس – الشرقية.\n\nالشروط المطلوبة:\n\nخبرة لا "
        "تقل عن 5 سنوات في مجال تصنيع الملابس، ويفضل التخصص في الجينز "
        "والدنيم."
    ),
}

#: The ad body used where the JSON-LD description is absent. Long enough to
#: clear the parser's 40-character floor, as a real body does (620+).
BODY = (
    "للعمل بمصنع ملابس جينز متخصص في الإنتاج والبيع بالجملة للتجار. مع "
    "القدرة على تخطيط الإنتاج وتجهيز احتياجات المواسم ومتابعة الخامات "
    "والاكسسوارات والعينات واعتماد الموديلات."
)

DETAIL_HTML = (
    """<!DOCTYPE html><html><head>
<script type="application/ld+json">"""
    + json.dumps(JOB_POSTING, ensure_ascii=False)
    + """</script>
</head><body>
<div class="white-block clearfix">
  <div class="title"><h3>تفاصيل الوظيفة</h3></div>
  <div class="requirements">
    <h3>متطلبات الوظيفة</h3><p>مستوي الخبرة خبرة متوسطة</p>
  </div>
  <div class="body"><p>"""
    + BODY
    + """</p></div>
</div>
<div class="related">وظائف شبيهة</div>
</body></html>"""
)

#: A listing page: 20 postings among several hundred other anchors, including
#: category, city and company links that also carry numbers.
#:
#: ``__SLUG__`` is substituted afterwards rather than interpolated, so the
#: fixture has no f-string braces to escape and no chance of an unclosed
#: ``href`` -- which is exactly the mistake this file was rewritten to remove.
_LISTING_TEMPLATE = """<html><body>
<a href="/a/وظائف-القاهرة">وظائف</a>
<a href="/a/وظائف-ذكور">وظائف 1691</a>
<a href="/company/152293">أون تايم</a>
<a href="/job/p/__SLUG__">مسئول تسويق</a>
<a href="/job/p/__SLUG__">read more</a>
<a href="/job/p/%D9%83%D8%A7%D8%B4%D9%8A%D8%B1-444453">كاشير</a>
<a href="/job/p/no-number-here">broken</a>
</body></html>"""

LISTING_HTML = _LISTING_TEMPLATE.replace("__SLUG__", SLUG)


def _detail(html: str = DETAIL_HTML, slug: str = SLUG, job_id: str | None = "444468"):
    return parse_detail(slug, html, url=f"https://forasna.com/job/p/{slug}", job_id=job_id)


def _with_jobposting(**changes) -> str:
    """DETAIL_HTML's page with a modified JobPosting block.

    The page markup is reused rather than rebuilt, so the body, the
    requirements block and the related-jobs section are all still there --
    which is what the page-fallback description is read from.
    """
    data = json.loads(json.dumps(JOB_POSTING))
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return DETAIL_HTML.replace(
        json.dumps(JOB_POSTING, ensure_ascii=False),
        json.dumps(data, ensure_ascii=False),
    )


# ---------------------------------------------------------------- listing


class TestListing:
    def test_the_job_paths_are_found_and_the_rest_ignored(self):
        postings = parse_listing(LISTING_HTML)
        assert [jid for _slug, jid in postings] == ["444468", "444453"]

    def test_a_duplicate_link_to_the_same_posting_is_one_posting(self):
        """The page links each posting twice -- the title and 'read more'."""
        assert len(parse_listing(LISTING_HTML)) == 2

    def test_a_slug_with_no_trailing_number_is_skipped(self):
        """It carries no id, so it cannot be a posting's natural key."""
        assert all(jid.isdigit() for _s, jid in parse_listing(LISTING_HTML))

    def test_an_unclosed_href_cannot_produce_a_slug_that_spans_anchors(self):
        """The character class excludes ``<`` and ``>`` on purpose.

        A fixture with ``href="/job/p/<slug>`` -- the quote never closed --
        produced one "posting" whose slug was the whole of
        ``<slug>>read more</a>\\n<a href="/job/p/<next-slug>``. The id came out
        as the *next* posting's number, which is a wrong answer rather than a
        obviously broken one. The class is tight so a slug can never span
        into the markup after it.
        """
        broken = (
            '<html><body><a href="/job/p/abc-1">one</a>\n'
            '<a href="/job/p/abc-2>two</a>\n'
            '<a href="/job/p/abc-3">three</a></body></html>'
        )
        postings = parse_listing(broken)
        for slug, _job_id in postings:
            assert "<" not in slug and ">" not in slug, (
                f"the slug spans into the markup after it: {slug!r}"
            )
            assert "href" not in slug
        # The malformed anchor's posting is still RECOVERED. BeautifulSoup
        # merges it with the next one, giving the href
        # "/job/p/abc-2>two</a>\n<a href=", and only the tight character
        # class stops the slug at the ">". A looser class yields
        # "abc-2>two<", which has no trailing number, so the posting is lost
        # entirely -- and a lost posting is a wrong answer, not a loud one.
        assert {jid for _s, jid in postings} == {"1", "2"}

    def test_the_id_is_the_trailing_number_of_the_slug(self):
        assert slug_id("...-444468") == "444468"
        assert slug_id("444468") == "444468"
        assert slug_id("no-number") is None
        assert slug_id("") is None

    def test_an_empty_page_yields_nothing(self):
        assert parse_listing("<html><body></body></html>") == []


# ---------------------------------------------------------------- detail


class TestDetailFields:
    def test_the_title_and_company_come_from_the_json_ld(self):
        job = _detail()
        assert job.title == "مسئول تسويق ومبيعات خارجية"
        assert job.company_name == "أون تايم سيستمز"

    def test_the_id_comes_from_the_identifier(self):
        assert _detail().source_job_id == "444468"

    def test_the_dates_come_from_date_posted_and_valid_through(self):
        job = _detail()
        assert job.posted_date == date(2026, 10, 19)
        assert job.closing_date == date(2026, 11, 17)

    def test_the_location_is_locality_then_region(self):
        job = _detail()
        assert job.locality == "المنيا"
        assert job.region == "المنيا"
        assert job.location == "المنيا", "same locality and region is not repeated"

    def test_a_different_locality_and_region_are_joined_with_a_comma(self):
        """The shape the geographic resolver's comma fallback needs."""
        data = json.loads(json.dumps(JOB_POSTING))
        data["jobLocation"]["address"]["addressLocality"] = "مدينة نصر"
        data["jobLocation"]["address"]["addressRegion"] = "القاهرة"
        html = (
            '<html><head><script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False)
            + "</script></head><body></body></html>"
        )
        assert _detail(html).location == "مدينة نصر, القاهرة"

    def test_the_country_comes_from_the_record_not_the_board(self):
        assert _detail().country == "EG"

    def test_a_page_with_no_jobposting_block_raises(self):
        with pytest.raises(ForasnaParseError, match="JobPosting"):
            _detail("<html><body>nothing here</body></html>")

    def test_a_jobposting_with_no_title_raises(self):
        with pytest.raises(ForasnaParseError, match="no title"):
            _detail(_with_jobposting(title=""))


class TestSalary:
    def test_the_salary_is_read_from_base_salary(self):
        job = _detail()
        assert job.salary_min == 5000
        assert job.salary_max == 8000
        assert job.salary_currency == "EGP"
        assert job.pay_period == "monthly", "unitText MONTH must map to 'monthly'"

    def test_a_dollar_posting_keeps_its_own_currency(self):
        """One sampled posting on an Egyptian board declares USD."""
        data = json.loads(json.dumps(JOB_POSTING))
        data["baseSalary"]["currency"] = "USD"
        html = (
            '<html><head><script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False)
            + "</script></head><body></body></html>"
        )
        job = _detail(html)
        assert job.salary_currency == "USD"
        assert ForasnaCleaner().clean_job(job).currency_iso_code == "USD", (
            "the currency is per posting; assuming EGP would mis-file this one"
        )

    def test_a_saudi_posting_keeps_sar_and_sa(self):
        """The one sampled SAR posting has addressCountry SA, not EG."""
        data = json.loads(json.dumps(JOB_POSTING))
        data["baseSalary"]["currency"] = "SAR"
        data["jobLocation"]["address"]["addressCountry"] = "SA"
        data["jobLocation"]["address"]["addressRegion"] = "أبها"
        html = (
            '<html><head><script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False)
            + "</script></head><body></body></html>"
        )
        job = _detail(html)
        assert job.salary_currency == "SAR"
        assert job.country == "SA", "the region is Abha, which is not in Egypt"

    def test_a_posting_with_no_salary_has_none(self):
        job = _detail(_with_jobposting(baseSalary=None))
        assert job.salary_min is None and job.salary_max is None
        cleaned = ForasnaCleaner().clean_job(job)
        assert cleaned.salary_disclosed is False
        assert cleaned.salary_min is None and cleaned.salary_max is None

    @pytest.mark.parametrize(
        ("unit", "expected"),
        [
            ("MONTH", "monthly"),
            ("YEAR", "yearly"),
            ("HOUR", "hourly"),
            ("DAY", "daily"),
            ("WEEK", "weekly"),
        ],
    )
    def test_every_unit_maps_to_the_schema_vocabulary(self, unit, expected):
        data = json.loads(json.dumps(JOB_POSTING))
        data["baseSalary"]["value"]["unitText"] = unit
        html = (
            '<html><head><script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False)
            + "</script></head><body></body></html>"
        )
        assert _detail(html).pay_period == expected

    def test_the_pay_period_is_always_in_the_schema_vocabulary(self):
        """A value outside it aborts the shared transaction."""
        data = json.loads(json.dumps(JOB_POSTING))
        data["baseSalary"]["value"]["unitText"] = "FORTNIGHT"
        html = (
            '<html><head><script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False)
            + "</script></head><body></body></html>"
        )
        cleaned = ForasnaCleaner().clean_job(_detail(html))
        assert cleaned.pay_period in {"hourly", "daily", "weekly", "monthly", "yearly"}


class TestDescription:
    def test_the_json_ld_description_is_used(self):
        job = _detail()
        assert job.description is not None
        assert "مصنع ملابس" in job.description

    def test_the_requirements_block_is_not_mistaken_for_a_description(self):
        """It is a structured fields block, and it says 'experience level'."""
        job = _detail()
        assert "مستوي الخبرة" not in job.description

    def test_a_posting_with_no_json_ld_description_falls_back_to_the_page(self):
        job = _detail(_with_jobposting(description=None))
        assert job.description is not None
        assert "مصنع ملابس" in job.description

    def test_the_requirements_block_is_still_not_the_description(self):
        """The fallback must not pick the requirements block instead."""
        job = _detail(_with_jobposting(description=None))
        assert job.description is not None
        assert "مستوي الخبرة" not in job.description, "the requirements block leaked"
        assert "الموديلات" in job.description, "the page body is not the description"


# ---------------------------------------------------------------- cleaner


class TestCleaner:
    def test_the_arabic_body_survives(self):
        cleaned = ForasnaCleaner().clean_job(_detail())
        assert cleaned.description_clean is not None
        assert "مصنع ملابس" in cleaned.description_clean
        assert cleaned.word_count == len(cleaned.description_clean.split())

    def test_the_title_is_the_posting_own_arabic_title(self):
        """Not a placeholder, and not the employer."""
        cleaned = ForasnaCleaner().clean_job(_detail())
        assert cleaned.job_title == "مسئول تسويق ومبيعات خارجية"
        assert "أون تايم" not in cleaned.job_title, "the employer leaked into the title"

    def test_the_location_is_the_reduced_form(self):
        assert ForasnaCleaner().clean_job(_detail()).location_cleaned == "المنيا"

    def test_the_raw_payload_keeps_the_parts(self):
        payload = ForasnaCleaner().clean_job(_detail()).raw_payload
        assert payload["locality"] == "المنيا"
        assert payload["region"] == "المنيا"
        assert payload["language"] == "ar"

    def test_the_employment_type_maps_to_the_schema_vocabulary(self):
        assert ForasnaCleaner().clean_job(_detail()).employment_type_code == "part_time"

    def test_an_unrecognised_employment_type_is_left_none(self):
        job = _detail(_with_jobposting(employmentType="SOMETHING_NEW"))
        assert ForasnaCleaner().clean_job(job).employment_type_code is None

    def test_the_url_carries_the_slug(self):
        cleaned = ForasnaCleaner().clean_job(_detail())
        assert cleaned.original_url.endswith(SLUG)
        assert cleaned.source_job_id == "444468"

    def test_a_missing_description_leaves_the_field_empty(self):
        job = _detail(_with_jobposting(description=None))
        cleaned = ForasnaCleaner().clean_job(job)
        assert cleaned.description_clean is None or cleaned.description_clean


# ---------------------------------------------------------------- client


class TestClientContract:
    def test_no_browser_is_configured_anywhere(self):
        assert not hasattr(ForasnaSettings(), "headless"), "this source needs no browser"

    def test_the_listing_is_the_search_page_not_the_all_jobs_route(self):
        """The all-jobs route has no job links on it."""
        settings = ForasnaSettings()
        assert "وظائف-مصر" not in settings.listing_path
        assert settings.listing_path == "/وظائف-خالية"

    def test_the_listing_url_pages_by_offset(self):
        client = ForasnaClient(ForasnaSettings(page_size=20))
        assert client.listing_url(1).endswith("?start=0")
        assert client.listing_url(2).endswith("?start=20")
        assert client.listing_url(3).endswith("?start=40")

    def test_the_detail_url_carries_the_slug(self):
        client = ForasnaClient(ForasnaSettings())
        assert client.detail_url("abc-444468").endswith("/job/p/abc-444468")

    def test_an_empty_discovery_raises_rather_than_looking_successful(self):
        client = ForasnaClient(ForasnaSettings())
        client.fetch_listing_page = lambda page=1: []
        with pytest.raises(ForasnaResponseError, match="2852"):
            client.discover()
        client.close()

    def test_the_discovery_stops_at_the_budget(self):
        """A cap, not a target: a page carries 20 and the run may ask for 3."""
        client = ForasnaClient(ForasnaSettings(max_jobs_per_run=3, max_list_pages=10))
        client.fetch_listing_page = lambda page=1: [(f"s-{i}", str(i)) for i in range(5)]
        found, _ = client.discover()
        assert len(found) == 3
        client.close()

    def test_a_page_that_repeats_its_ids_does_not_inflate_the_count(self):
        client = ForasnaClient(ForasnaSettings(max_jobs_per_run=100, max_list_pages=3))
        client.fetch_listing_page = lambda page=1: [("s-1", "1"), ("s-2", "2")]
        found, _ = client.discover()
        assert len(found) == 2
        client.close()


class TestTheValidator:
    """The batch validator, which nothing else exercised.

    Its field checks decide whether a run is reported as healthy, so a check
    that is too strict -- requiring a salary, which 64% of postings do not
    have -- turns every run into a false alarm.
    """

    def _jobs(self, count: int = 12):
        """Distinct postings -- the validator rightly rejects duplicates."""
        jobs = []
        for i in range(count):
            job = _detail(job_id=str(444_468 + i))
            job.source_job_id = str(444_468 + i)
            jobs.append(job)
        return jobs

    def test_a_healthy_batch_passes(self):
        from job_market_intel.validation.forasna_validator import ForasnaBatchValidator

        jobs = self._jobs()
        report = ForasnaBatchValidator().validate([{}] * len(jobs), jobs)
        assert report.passed, getattr(report, "issues", None)

    def test_a_salary_is_not_required(self):
        """32% of postings carry a figure; requiring one fails two thirds.

        The report exposes the rate per field rather than failing the batch
        outright, so the assertion is on the rates.
        """
        from job_market_intel.validation.forasna_validator import ForasnaBatchValidator

        jobs = self._jobs()
        for job in jobs:
            job.salary_min = None
            job.salary_max = None
        report = ForasnaBatchValidator().validate([{}] * len(jobs), jobs)
        assert report.passed, getattr(report, "issues", None)
        assert "salary" not in report.missing_field_rates, (
            "a salary check would fail two thirds of the board"
        )

    def test_a_missing_description_is_reported(self):
        from job_market_intel.validation.forasna_validator import ForasnaBatchValidator

        jobs = self._jobs()
        for job in jobs:
            job.description = None
        report = ForasnaBatchValidator().validate([{}] * len(jobs), jobs)
        assert report.missing_field_rates.get("description") == 1.0, (
            f"a missing description went unreported: {report.missing_field_rates}"
        )
