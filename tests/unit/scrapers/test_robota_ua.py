"""Unit tests for the Robota.ua (robota.ua, Ukraine) scraper.

All facts pinned here were measured against the live GraphQL API on
2026-11-28:

  * ``publishedVacancies`` returns ``{totalCount, items}``; 100 items per page
    were accepted and pages did not overlap.
  * ``salary`` is ``{amount, amountFrom, amountTo, comment, isNet, currency}``
    with ``currency`` an ISO string (``"UAH"``); a single-value ad leaves
    ``amountFrom``/``amountTo`` null and fills ``amount``.
  * ``workTypes`` are ``REMOTE``/``HYBRID``/``OFFICE``; ``employmentTypes``
    are ``FULL_TIME``/``PART_TIME``/``PROJECT_BASED``/``SHIFT``.
  * ``subrubrics`` are English occupation names (``"Cash Transactions"``).
  * ``firstPublishedAt`` carries 7 fractional digits
    (``2022-08-02T10:43:49.7130000+03:00``); ``sortDate`` carries 3
    (``2026-11-27T23:01:00.973``).
  * ``formApplyCustomUrl`` is empty on on-platform ads.

No test touches the network.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from job_market_intel.scrapers.robota_ua import (
    RawRobotaUaJob,
    RobotaUaClient,
    RobotaUaParser,
    RobotaUaPipeline,
    RobotaUaResponseError,
    RobotaUaSettings,
)
from job_market_intel.scrapers.robota_ua.exceptions import RobotaUaParseError
from job_market_intel.scrapers.robota_ua.parser import (
    HOME_COUNTRY,
    HOME_CURRENCY,
    _salary,
    build_location,
    extract_skills,
    map_employment_type,
    map_work_type,
    parse_date,
)


def _item(**overrides):
    base = {
        "id": "11305583",
        "title": "Продавець в магазин",
        "description": "Короткий опис",
        "fullDescription": "<p>Повний <strong>опис</strong> вакансії з деталями.</p>",
        "sortDate": "2026-11-27T23:01:00.973",
        "createdAt": "2026-08-14T10:00:00.1",
        "firstPublishedAt": "2026-08-14T10:00:00.7130000+03:00",
        "salary": {
            "amount": 20000,
            "amountFrom": 20000,
            "amountTo": 25000,
            "comment": "",
            "isNet": False,
            "currency": "UAH",
        },
        "company": {
            "id": "352769",
            "name": "Скарбниця",
            "logoUrl": "https://company-logo-frankfurt.rabota.ua/352769.png",
            "companyUrl": "http://www.skarb.com.ua/",
        },
        "city": {
            "id": "1",
            "name": "Kyiv",
            "slug": "kyiv",
            "region": {"id": "1", "name": "Kyiv oblast"},
        },
        "address": {"name": ""},
        "schedules": [{"name": "office"}, {"name": "full-time"}],
        "subrubrics": [
            {"id": "167", "name": "Cash Transactions"},
            {"id": "158", "name": "Loans"},
            {"id": "167", "name": "Cash Transactions"},
        ],
        "employmentTypes": ["FULL_TIME"],
        "workTypes": ["OFFICE"],
        "isActive": True,
        "anonymous": False,
        "isAgency": False,
        "formApplyCustomUrl": "",
    }
    base.update(overrides)
    return base


def _raw(**overrides) -> RawRobotaUaJob:
    return RawRobotaUaJob.from_item(_item(**overrides), base_url="https://robota.ua")


class TestRawModel:
    def test_url_is_built_from_the_id(self):
        raw = _raw()
        assert raw.job_id == "11305583"
        assert raw.url == "https://robota.ua/vacancy/11305583"

    @pytest.mark.parametrize(
        "item",
        [
            {"id": "1"},
            {"title": "x"},
            {"id": "", "title": "x"},
            {"id": "1", "title": "   "},
        ],
    )
    def test_items_without_id_or_title_are_rejected(self, item):
        with pytest.raises(ValueError):
            RawRobotaUaJob.from_item(item, base_url="https://robota.ua")


class TestDates:
    def test_three_fraction_digits_without_timezone(self):
        assert parse_date("2026-11-27T23:01:00.973") == datetime(2026, 11, 27)

    def test_seven_fraction_digits_with_timezone(self):
        assert parse_date("2022-08-02T10:43:49.7130000+03:00") == datetime(2022, 8, 2)

    def test_z_suffix(self):
        assert parse_date("2026-01-02T03:04:05Z") == datetime(2026, 1, 2)

    @pytest.mark.parametrize("value", [None, "", "not-a-date", "2026-13-40T00:00:00"])
    def test_unreadable_dates_are_none(self, value):
        assert parse_date(value) is None


class TestEnums:
    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            (["FULL_TIME"], "full_time"),
            (["PART_TIME"], "part_time"),
            (["PROJECT_BASED"], "contract"),
            (["SHIFT"], None),
            (["PROJECT_BASED", "SHIFT"], "contract"),
            (["FULL_TIME", "PART_TIME"], None),
            ([], None),
            (None, None),
        ],
    )
    def test_employment_mapping(self, values, expected):
        assert map_employment_type(values) == expected

    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            (["OFFICE"], "on_site"),
            (["HYBRID"], "hybrid"),
            (["REMOTE"], "remote_country"),
            (["OFFICE", "REMOTE"], "remote_country"),
            (["OFFICE", "HYBRID"], "hybrid"),
            ([], None),
            (None, None),
        ],
    )
    def test_work_type_mapping(self, values, expected):
        assert map_work_type(values) == expected


class TestLocationAndSkills:
    def test_a_city_gets_the_country(self):
        assert build_location("Kyiv", "on_site") == f"Kyiv, {HOME_COUNTRY}"

    def test_a_remote_ad_is_labelled_remote(self):
        assert build_location("Kyiv", "remote_country") == f"Remote, {HOME_COUNTRY}"
        assert build_location("Kyiv", "hybrid") == f"Kyiv, {HOME_COUNTRY}"

    def test_a_missing_city_falls_back_to_the_country(self):
        assert build_location(None, "on_site") == HOME_COUNTRY

    def test_subrubrics_become_lowercased_unique_skills(self):
        skills = extract_skills(_item())
        assert skills == ["cash transactions", "loans"]

    def test_no_subrubrics_is_an_empty_list(self):
        assert extract_skills({"subrubrics": None}) == []


class TestSalary:
    def test_a_range_is_read(self):
        assert _salary(_item()) == (20000, 25000, "UAH")

    def test_a_single_amount_fills_both_bounds(self):
        item = _item(
            salary={"amount": 30000, "amountFrom": None, "amountTo": None, "currency": "UAH"}
        )
        assert _salary(item) == (30000, 30000, "UAH")

    def test_a_missing_salary_is_undisclosed(self):
        item = _item(salary=None)
        assert _salary(item) == (None, None, HOME_CURRENCY)

    def test_zero_is_not_a_salary(self):
        item = _item(salary={"amount": 0, "amountFrom": 0, "amountTo": 0, "currency": "UAH"})
        assert _salary(item) == (None, None, "UAH")

    def test_reversed_bounds_are_swapped(self):
        item = _item(
            salary={"amount": None, "amountFrom": 50000, "amountTo": 40000, "currency": "UAH"}
        )
        assert _salary(item) == (40000, 50000, "UAH")

    def test_an_unknown_currency_falls_back_to_uah(self):
        item = _item(salary={"amount": 100, "amountFrom": 100, "amountTo": 200, "currency": ""})
        assert _salary(item) == (100, 200, HOME_CURRENCY)


class TestParser:
    def test_the_contract_is_fully_populated(self):
        job = RobotaUaParser().parse_job(_raw())
        assert job.source_job_id == "11305583"
        assert job.job_title == "Продавець в магазин"
        assert job.company_name == "Скарбниця"
        assert job.company_logo_url == "https://company-logo-frankfurt.rabota.ua/352769.png"
        assert job.location_cleaned == f"Kyiv, {HOME_COUNTRY}"
        assert job.remote_work_type_code == "on_site"
        assert job.employment_type_code == "full_time"
        assert job.salary_min == 20000 and job.salary_max == 25000
        assert job.salary_disclosed is True
        assert job.currency_iso_code == "UAH"
        assert job.pay_period == "monthly"
        assert job.posting_date == datetime(2026, 8, 14)
        assert job.closing_date is None
        assert job.description_clean and "Повний" in job.description_clean
        assert job.word_count > 0
        assert job.skills == ["cash transactions", "loans"]
        assert job.apply_url == job.original_url == "https://robota.ua/vacancy/11305583"

    def test_an_anonymous_ad_gets_a_confidential_employer(self):
        job = RobotaUaParser().parse_job(_raw(company=None, anonymous=True))
        assert job.company_name == "Confidential Employer"
        assert job.company_logo_url is None

    def test_a_remote_ad_is_country_remote(self):
        job = RobotaUaParser().parse_job(_raw(workTypes=["REMOTE"]))
        assert job.remote_work_type_code == "remote_country"
        assert job.location_cleaned == f"Remote, {HOME_COUNTRY}"

    def test_a_project_based_ad_is_contract(self):
        job = RobotaUaParser().parse_job(_raw(employmentTypes=["PROJECT_BASED", "SHIFT"]))
        assert job.employment_type_code == "contract"

    def test_a_multi_valued_employment_type_is_none_but_kept_raw(self):
        job = RobotaUaParser().parse_job(_raw(employmentTypes=["FULL_TIME", "PART_TIME"]))
        assert job.employment_type_code is None
        assert job.raw_payload["employment_types_raw"] == ["FULL_TIME", "PART_TIME"]

    def test_a_custom_apply_url_wins(self):
        job = RobotaUaParser().parse_job(_raw(formApplyCustomUrl="https://apply.example.com/x"))
        assert job.apply_url == "https://apply.example.com/x"
        assert job.original_url == "https://robota.ua/vacancy/11305583"

    def test_no_description_is_none_not_the_title(self):
        job = RobotaUaParser().parse_job(_raw(fullDescription=None, description=None))
        assert job.description_clean is None
        assert job.word_count == 0

    def test_a_missing_title_is_raised(self):
        raw = RawRobotaUaJob(job_id="1", url="https://robota.ua/vacancy/1", payload={"title": " "})
        with pytest.raises(RobotaUaParseError):
            RobotaUaParser().parse_job(raw)

    def test_one_bad_item_does_not_drop_the_good_ones(self):
        good = _raw()
        bad = RawRobotaUaJob(job_id="2", url="https://robota.ua/vacancy/2", payload={"title": ""})
        jobs = RobotaUaParser().parse_jobs([good, bad])
        assert len(jobs) == 1
        assert jobs[0].source_job_id == "11305583"


class TestClientDiscovery:
    @staticmethod
    def _client(**kwargs) -> RobotaUaClient:
        settings = RobotaUaSettings(fetch_delay_seconds=0, page_size=2, **kwargs)
        return RobotaUaClient(settings=settings)

    def test_items_are_deduped_and_the_budget_is_applied(self):
        client = self._client(max_jobs_per_run=3, max_pages=5)
        client._query_page = lambda page, count: {
            "totalCount": 5,
            "items": [_item(id="1"), _item(id="1"), _item(id="2"), _item(id="3"), _item(id="4")],
        }
        jobs, pages = client.fetch_raw_jobs()
        assert [j.job_id for j in jobs] == ["1", "2", "3"]
        assert pages == 1

    def test_excluded_ids_are_skipped(self):
        client = self._client(max_jobs_per_run=10, max_pages=5)
        client._query_page = lambda page, count: {
            "totalCount": 4,
            "items": [_item(id="1"), _item(id="2"), _item(id="3"), _item(id="4")],
        }
        jobs, _ = client.fetch_raw_jobs(exclude_ids={"2", "4"})
        assert [j.job_id for j in jobs] == ["1", "3"]

    def test_pages_advance_until_the_budget_is_full(self):
        calls: list[int] = []

        def fake(page, count):
            calls.append(page)
            return {
                "totalCount": 100,
                "items": [_item(id=f"{page}{i}") for i in range(2)],
            }

        client = self._client(max_jobs_per_run=5, max_pages=10)
        client._query_page = fake
        jobs, pages = client.fetch_raw_jobs()
        assert len(jobs) == 5
        assert calls == [1, 2, 3]
        assert pages == 3

    def test_total_count_stops_the_walk(self):
        client = self._client(max_jobs_per_run=10, max_pages=10)
        seen_pages: list[int] = []

        def fake(page, count):
            seen_pages.append(page)
            return {"totalCount": 3, "items": [_item(id=str(page))]}

        client._query_page = fake
        jobs, pages = client.fetch_raw_jobs()
        assert [j.job_id for j in jobs] == ["1", "2"]
        assert seen_pages == [1, 2]
        assert pages == 2

    def test_no_unseen_items_with_exclusions_is_a_covered_corpus(self):
        client = self._client(max_jobs_per_run=10, max_pages=3)
        client._query_page = lambda page, count: {"totalCount": 2, "items": [_item(id="1")]}
        jobs, pages = client.fetch_raw_jobs(exclude_ids={"1"})
        assert jobs == []
        assert pages >= 1

    def test_an_empty_board_without_exclusions_raises(self):
        client = self._client(max_jobs_per_run=10, max_pages=3)
        client._query_page = lambda page, count: {"totalCount": 0, "items": []}
        with pytest.raises(RobotaUaResponseError, match="zero usable postings"):
            client.fetch_raw_jobs()

    def test_items_without_titles_are_skipped(self):
        client = self._client(max_jobs_per_run=10, max_pages=3)
        client._query_page = lambda page, count: {
            "totalCount": 2,
            "items": [{"id": "1"}, _item(id="2")],
        }
        jobs, _ = client.fetch_raw_jobs()
        assert [j.job_id for j in jobs] == ["2"]


class TestPipelineDryRun:
    class _Client:
        def __init__(self, raws, pages=1):
            self.raws = raws
            self.pages = pages

        def fetch_raw_jobs(self, exclude_ids=None):
            return self.raws, self.pages

    def test_a_dry_run_parses_without_persisting(self):
        client = self._Client([_raw()], pages=2)
        result = RobotaUaPipeline(settings=RobotaUaSettings(), client=client).run(store_db=False)
        assert result.pages_scraped == 2
        assert result.raw_count == 1
        assert result.parsed_count == 1
        assert result.cleaned_count == 1
        assert result.validation_passed is True
        assert result.inserted_count == 0
        assert result.failed_count == 0

    def test_an_empty_covered_run_is_a_passing_noop(self):
        client = self._Client([], pages=1)
        result = RobotaUaPipeline(settings=RobotaUaSettings(), client=client).run(store_db=False)
        assert result.validation_passed is True
        assert result.raw_count == 0
        assert result.parsed_count == 0

    def test_zero_parsed_rows_fail_validation(self):
        bad = RawRobotaUaJob(job_id="1", url="https://robota.ua/vacancy/1", payload={"title": ""})
        client = self._Client([bad])
        result = RobotaUaPipeline(settings=RobotaUaSettings(), client=client).run(store_db=False)
        assert result.validation_passed is False
        assert any("Zero jobs successfully parsed" in issue for issue in result.issues)
