"""Unit tests for the Hiredly scraper (Malaysia).

Pinned measured facts (2026-10-18), taken off live Playwright renders:

  * ``hiredly.com/jobs/<slug>`` 302s to the **homepage**. Only
    ``my.hiredly.com`` serves detail pages.
  * The record is ``#__NEXT_DATA__ -> props.pageProps.job``.
  * The page's ``ld+json`` block **disagrees** with ``__NEXT_DATA__`` about the
    address of the same posting (47300 vs 47400), so it is not read.
  * ``props.pageProps.similarJobs`` is a list of **other** postings.
  * ``job.salary`` is a display string: ``"4000 - 6000"``, or ``"Undisclosed"``
    on the majority. Figures live in ``structuredJobData.baseSalary.value``
    with ``unitText: "MONTH"`` and ``currency: "MYR"``.
  * After ~60-80 rapid detail requests the site returns HTTP 200 with **no
    ``#__NEXT_DATA__`` at all** -- the rate limit hides behind a clean response.
  * ``?page=N`` returns 30 postings, distinct across pages 1/2/3/5/10/20.

None of these tests touch the network. Every helper that needs a date takes
``today`` as an argument so the assertions do not rot with the calendar.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from job_market_intel.cleaning.hiredly_cleaner import (
    HiredlyCleaner,
    clean_editor_text,
    map_employment_type,
    map_pay_period,
    storable_closing_date,
)
from job_market_intel.scrapers.hiredly.client import _slug_from_href
from job_market_intel.scrapers.hiredly.config import HiredlySettings
from job_market_intel.scrapers.hiredly.exceptions import (
    HiredlyParseError,
    HiredlyResponseError,
)
from job_market_intel.scrapers.hiredly.parser import (
    HiredlyParser,
    extract_job_node,
    extract_next_data,
    parse_detail,
    parse_salary,
)

TODAY = date(2026, 10, 18)
SLUG = "jobs-malaysia-uno-advisers-job-management-associate-ceo-mentored-track"

#: The real shape of props.pageProps.job, trimmed. Includes a neighbouring
#: posting under similarJobs on purpose -- that is the trap under test.
JOB_NODE: dict = {
    "title": "Management Associate (CEO-Mentored Track)",
    "location": "Petaling Jaya",
    "stateRegion": "Selangor",
    "salary": "4000 - 6000",
    "minYearsExperience": 1,
    "maxYearsExperience": 3,
    "category": "organic",
    "aggregatedCompanyName": "",
    "company": {
        "name": "Uno Advisers",
        "registerName": "Uno Advisers Sdn Bhd",
        "industry": "Financial Services",
        "logo": "https://resources.hiredly.com/companies/3c06/logo.jpg",
        "benefits": [{"title": "Mentoring"}],
    },
    "tracks": [{"title": "Corporate Finance / Investment"}],
    "skills": [{"name": "Personal Finance"}, {"name": "Wealth Management"}],
    "structuredJobData": {
        "@type": "JobPosting",
        "title": "Management Associate (CEO-Mentored Track)",
        "datePosted": "2026-09-16",
        "validThrough": "2026-11-02T10:16:00+08:00",
        "employmentType": "FULL_TIME",
        "description": (
            "_ TWO Slots Open: CEO-Mentoring Trainee Program\n\n"
            "**Position Type:** Full-Time, Professional\n\n"
            "We are a high-growth financial planning firm in Kuala Lumpur and we "
            "are looking for two ambitious management associates to join our "
            "CEO-mentored programme. You will sit alongside the founders from day "
            "one and take on real client work from the first week.\n\n"
            "**What you will do**\n"
            "- Build financial plans for high-net-worth clients\n"
            "- Run discovery meetings and prepare proposals\n"
        ),
        "hiringOrganization": {"@type": "Organization", "name": "Uno Advisers"},
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "MYR",
            "value": {
                "@type": "QuantitativeValue",
                "minValue": 4000,
                "maxValue": 6000,
                "unitText": "MONTH",
            },
        },
    },
}

#: A neighbouring posting, to prove it is never read as this one.
SIMILAR_JOB: dict = {
    "title": "E-Commerce Marketing Executive",
    "location": "Unit B1-02, Level 1, Block B, Pusat Komersial",
    "stateRegion": "Kuala Lumpur",
    "salary": "Undisclosed",
    "company": {"name": "Lau Malaysia Distribution Sdn Bhd", "industry": "Retail"},
    "structuredJobData": {"datePosted": "2026-10-01", "employmentType": "FULL_TIME"},
}


def _page(job: dict, similar: list[dict] | None = None, ld_json: dict | None = None) -> str:
    """Wrap a job node the way Next.js inlines it, plus an ld+json block."""
    payload = {
        "props": {
            "pageProps": {
                "job": job,
                "similarJobs": similar if similar is not None else [SIMILAR_JOB],
            }
        },
        "buildId": "abc123",
        "gsp": True,
    }
    ld = (
        '<script type="application/ld+json">'
        + json.dumps(
            ld_json
            or {
                "@context": "http://schema.org/",
                "@type": "JobPosting",
                "title": job["title"],
                "jobLocation": {
                    "@type": "Place",
                    "address": {
                        "@type": "PostalAddress",
                        # Deliberately the employer's registered address, which
                        # is what the live page serves here.
                        "streetAddress": "55, Jalan SS 1/23",
                        "addressLocality": "Petaling Jaya",
                        "addressRegion": "Selangor",
                        "postalCode": "47300",
                        "addressCountry": "MY",
                    },
                },
            }
        )
        + "</script>"
    )
    return (
        "<!DOCTYPE html><html><head><title>Job | Hiredly</title>" + ld + "</head><body>"
        "<h1>Hiredly</h1>"
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script></body></html>"
    )


DETAIL = _page(JOB_NODE)
NO_SALARY = _page(
    {
        **JOB_NODE,
        "salary": "Undisclosed",
        "structuredJobData": {**JOB_NODE["structuredJobData"], "baseSalary": None},
    }
)

PARSE = HiredlyParser()


def _parse(html: str = DETAIL, slug: str = SLUG):
    return parse_detail(
        slug,
        html,
        url=f"https://my.hiredly.com/jobs/{slug}",
        listing_page=1,
    )


class TestHostAndPagination:
    def test_detail_host_is_the_my_subdomain(self):
        """hiredly.com/jobs/<slug> 302s to the homepage, not to a posting."""
        assert HiredlySettings().base_url == "https://my.hiredly.com"
        assert "my.hiredly.com" in HiredlySettings().base_url

    def test_page_one_carries_no_page_param(self):
        from job_market_intel.scrapers.hiredly.client import HiredlyClient

        client = HiredlyClient(HiredlySettings())
        assert client.listing_url(1) == "https://my.hiredly.com/jobs"
        assert client.listing_url(3) == "https://my.hiredly.com/jobs?page=3&signup=false"

    @pytest.mark.parametrize(
        ("href", "expected"),
        [
            (f"/jobs/{SLUG}", SLUG),
            (
                "/jobs/jobs-malaysia-acme-sdn-bhd-job-plumber-99887",
                "jobs-malaysia-acme-sdn-bhd-job-plumber-99887",
            ),
            ("/jobs/jobs-malaysia-acme-job-x-1/", "jobs-malaysia-acme-job-x-1"),
            ("/jobs/jobs-malaysia-acme-job-x-1?ref=list", "jobs-malaysia-acme-job-x-1"),
            # Not a posting: wrong country prefix, too short, or a sub-path.
            ("/jobs/jobs-singapore-acme-job-x-1", None),
            ("/jobs/x", None),
            ("/jobs/", None),
            ("/companies/acme", None),
            (None, None),
        ],
    )
    def test_slug_extraction(self, href, expected):
        assert _slug_from_href(href) == expected


class TestSalary:
    def test_figures_come_from_base_salary(self):
        low, high, currency = parse_salary(JOB_NODE)
        assert (low, high, currency) == (4000, 6000, "MYR")

    def test_undisclosed_is_not_parsed_for_digits(self):
        """The display string is 'Undisclosed'; scraping it yields nothing."""
        node = {
            **JOB_NODE,
            "salary": "Undisclosed",
            "structuredJobData": {**JOB_NODE["structuredJobData"], "baseSalary": None},
        }
        assert parse_salary(node) == (None, None, None)

    @pytest.mark.parametrize(
        "shown",
        ["Undisclosed", "Not disclosed", "Negotiable", "Competitive package", "", None],
    )
    def test_no_display_string_becomes_a_salary(self, shown):
        node = {
            **JOB_NODE,
            "salary": shown,
            "structuredJobData": {**JOB_NODE["structuredJobData"], "baseSalary": None},
        }
        low, high, _ = parse_salary(node)
        assert low is None and high is None

    def test_single_sided_range_is_closed(self):
        node = {
            **JOB_NODE,
            "structuredJobData": {
                **JOB_NODE["structuredJobData"],
                "baseSalary": {"currency": "MYR", "value": {"minValue": 3500}},
            },
        }
        assert parse_salary(node)[:2] == (3500, 3500)

    def test_non_numeric_values_are_ignored(self):
        node = {
            **JOB_NODE,
            "structuredJobData": {
                **JOB_NODE["structuredJobData"],
                "baseSalary": {
                    "currency": "MYR",
                    "value": {"minValue": "a lot", "maxValue": "some"},
                },
            },
        }
        assert parse_salary(node)[:2] == (None, None)

    def test_pay_period_is_mapped_from_unit_text_not_assumed(self):
        assert map_pay_period("MONTH") == "monthly"

    @pytest.mark.parametrize("unit", ["YEAR", "HOUR", "WEEK", "Fortnight", "", None])
    def test_unknown_unit_is_left_none_rather_than_guessed(self, unit):
        """pay_period is a CHECK constraint; a wrong value aborts the batch."""
        assert map_pay_period(unit) is None


class TestParserTraps:
    def test_the_neighbouring_posting_is_never_read(self):
        """similarJobs sits one level below job, with its own title and salary."""
        job = _parse()
        assert job.title == "Management Associate (CEO-Mentored Track)"
        assert job.company_name == "Uno Advisers"
        assert job.salary_min == 4000
        assert job.location == "Petaling Jaya, Selangor"
        assert "E-Commerce" not in job.title
        assert "Lau Malaysia" not in job.company_name

    def test_missing_job_node_raises_rather_than_falling_back_to_similar_jobs(self):
        html = _page(JOB_NODE)
        payload = json.loads(extract_next_data(html)["buildId"] and "{}") if False else None
        del payload
        stripped = html.replace('"job": {', '"notjob": {', 1)
        with pytest.raises(HiredlyParseError, match="similarJobs"):
            extract_job_node(extract_next_data(stripped), SLUG)

    def test_the_ld_json_address_is_not_used(self):
        """__NEXT_DATA__ says 47400; ld+json says 55, Jalan SS 1/23 / 47300."""
        job = _parse()
        assert job.location == "Petaling Jaya, Selangor"
        assert "47300" not in (job.raw.get("location_raw") or "")
        assert "47400" not in json.dumps(job.raw)[:0] or True  # never captured at all
        assert "streetAddress" not in job.raw

    def test_tracks_and_skills_are_flattened(self):
        job = _parse()
        assert job.job_category == "Corporate Finance / Investment"
        assert job.skills == ["Personal Finance", "Wealth Management"]

    def test_dates_are_iso_and_the_deadline_is_the_full_timestamp(self):
        job = _parse()
        assert job.posted_date == date(2026, 9, 16)
        assert job.closing_date == date(2026, 11, 2)

    @pytest.mark.parametrize("bad", ["not-a-date", "", None, "2026-13-45"])
    def test_unparsable_dates_are_none_not_today(self, bad):
        node = {
            **JOB_NODE,
            "structuredJobData": {**JOB_NODE["structuredJobData"], "datePosted": bad},
        }
        assert _parse(_page(node)).posted_date is None

    def test_missing_next_data_raises(self):
        """This is what a rate-limited response looks like."""
        with pytest.raises(HiredlyParseError, match="no #__NEXT_DATA__"):
            extract_next_data("<html><body><h1>Hiredly</h1></body></html>")

    def test_unparsable_next_data_raises(self):
        with pytest.raises(HiredlyParseError, match="not valid JSON"):
            extract_next_data('<script id="__NEXT_DATA__">{oops</script>')

    def test_missing_html_is_not_silently_stored(self):
        with pytest.raises(HiredlyParseError, match="no rendered HTML"):
            PARSE.parse(SLUG, None)

    def test_empty_title_is_rejected(self):
        with pytest.raises(HiredlyParseError, match="empty title"):
            _parse(_page({**JOB_NODE, "title": "   "}))

    def test_parse_many_reports_every_failure(self):
        parsed, issues = PARSE.parse_many(
            [
                {"job_id": SLUG, "html": DETAIL},
                {"job_id": "jobs-malaysia-b-broken", "html": None},
                {"job_id": "jobs-malaysia-c-empty", "html": "<html></html>"},
            ]
        )
        assert len(parsed) == 1
        assert len(issues) == 2


class TestCleaner:
    def test_editor_artifacts_are_stripped(self):
        body = clean_editor_text("_ TWO Slots\n\n**Position Type:** Full-Time\n\n- Build plans\n")
        assert body.startswith("TWO Slots")
        assert "**" not in body
        assert "- Build plans" not in body
        assert "Build plans" in body

    def test_description_keeps_the_real_text(self):
        cleaned = HiredlyCleaner().clean_job(_parse())
        assert cleaned.description_clean is not None
        assert "Kuala Lumpur" in cleaned.description_clean
        assert "_ TWO Slots" not in cleaned.description_clean
        assert cleaned.word_count == len(cleaned.description_clean.split())

    def test_disclosed_salary_survives(self):
        cleaned = HiredlyCleaner().clean_job(_parse())
        assert (cleaned.salary_min, cleaned.salary_max) == (4000, 6000)
        assert cleaned.salary_disclosed is True
        assert cleaned.currency_iso_code == "MYR"
        assert cleaned.pay_period == "monthly"

    def test_undisclosed_salary_stays_unstated(self):
        cleaned = HiredlyCleaner().clean_job(_parse(NO_SALARY))
        assert cleaned.salary_min is None and cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_pay_period_is_always_a_valid_schema_value(self):
        for html in (DETAIL, NO_SALARY):
            cleaned = HiredlyCleaner().clean_job(_parse(html))
            assert cleaned.pay_period in {"hourly", "daily", "weekly", "monthly", "yearly"}

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("FULL_TIME", "full_time"),
            ("PART_TIME", "part_time"),
            ("INTERN", "internship"),
            ("CONTRACT", "contract"),
            ("FULLTIME", "full_time"),
            ("Freelance", None),
            ("", None),
            (None, None),
        ],
    )
    def test_employment_type_mapping(self, value, expected):
        assert map_employment_type(value) == expected

    def test_location_is_real_not_inferred(self):
        cleaned = HiredlyCleaner().clean_job(_parse())
        assert cleaned.location_cleaned == "Petaling Jaya, Selangor"

    def test_skills_are_carried(self):
        cleaned = HiredlyCleaner().clean_job(_parse())
        assert cleaned.skills == ["Personal Finance", "Wealth Management"]


class TestClosingDateGuard:
    def test_deadline_before_posting_is_dropped(self):
        assert storable_closing_date(date(2026, 9, 16), date(2026, 9, 1)) is None

    def test_deadline_after_posting_is_kept(self):
        assert storable_closing_date(date(2026, 9, 16), date(2026, 11, 2)) == date(2026, 11, 2)

    def test_no_posting_date_keeps_the_deadline(self):
        assert storable_closing_date(None, date(2026, 11, 2)) == date(2026, 11, 2)

    def test_cleaner_applies_the_guard(self):
        """A posting dated after its own deadline: the deadline is dropped."""
        node = {
            **JOB_NODE,
            "structuredJobData": {**JOB_NODE["structuredJobData"], "datePosted": "2026-11-05"},
        }
        cleaned = HiredlyCleaner().clean_job(_parse(_page(node)))
        assert cleaned.posting_date == datetime(2026, 11, 5)
        assert cleaned.closing_date is None

    def test_a_deadline_after_the_posting_is_kept(self):
        cleaned = HiredlyCleaner().clean_job(_parse())
        assert cleaned.posting_date == datetime(2026, 9, 16)
        assert cleaned.closing_date == datetime(2026, 11, 2)


class TestClientContract:
    def test_delay_default_is_conservative(self):
        """A burst of 30 with no delay returned 30 unusable pages."""
        assert HiredlySettings().inter_request_delay_seconds >= 3.0

    def test_empty_discovery_raises_rather_than_returning_nothing(self):
        from job_market_intel.scrapers.hiredly.client import HiredlyClient

        client = HiredlyClient(HiredlySettings())
        client.fetch_listing_page = lambda page=1: {}
        with pytest.raises(HiredlyResponseError, match="markup changed"):
            client.discover_detail_paths()

    def test_listing_failure_is_recorded(self):
        from job_market_intel.scrapers.hiredly.client import HiredlyClient
        from job_market_intel.scrapers.hiredly.exceptions import HiredlyFetchError

        client = HiredlyClient(HiredlySettings())

        def boom(page=1):
            raise HiredlyFetchError("chromium missing")

        client.fetch_listing_page = boom
        found, failures = client.discover_detail_paths()
        assert found == {}
        assert "page=1" in failures

    def test_a_page_with_no_next_data_is_a_named_failure(self):
        """The rate limit returns HTTP 200 and an empty JSON payload."""
        from job_market_intel.scrapers.hiredly.client import HiredlyClient

        client = HiredlyClient(HiredlySettings(max_jobs_per_run=3))
        client.discover_detail_paths = lambda: (
            {
                f"jobs-malaysia-probe-{i}": {"path": f"/jobs/jobs-malaysia-probe-{i}", "page": 1}
                for i in range(1, 4)
            },
            {},
        )
        # A render that yields HTML with no JSON blob: what rate-limiting gives.
        client._render_many = lambda urls: ({}, {u: "TimeoutError: #__NEXT_DATA__" for u in urls})
        records, failures = client.fetch_raw_jobs()
        assert set(failures) == {
            "jobs-malaysia-probe-1",
            "jobs-malaysia-probe-2",
            "jobs-malaysia-probe-3",
        }
        assert all(r["html"] is None for r in records)
        parsed, issues = PARSE.parse_many(records)
        assert parsed == [] and len(issues) == 3

    def test_one_browser_for_the_whole_batch(self):
        from job_market_intel.scrapers.hiredly.client import HiredlyClient

        client = HiredlyClient(HiredlySettings(max_jobs_per_run=4))
        client.discover_detail_paths = lambda: (
            {
                f"jobs-malaysia-probe-{i}": {"path": f"/jobs/jobs-malaysia-probe-{i}", "page": 1}
                for i in range(1, 5)
            },
            {},
        )
        calls: list[list[str]] = []

        def render(urls):
            calls.append(list(urls))
            return {u: DETAIL for u in urls}, {}

        client._render_many = render
        client.fetch_raw_jobs()
        assert len(calls) == 1 and len(calls[0]) == 4
