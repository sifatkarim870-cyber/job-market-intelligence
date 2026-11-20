"""Unit tests for the L'Express Petites Annonces (Mauritius) scraper.

Pinned measured facts (2026-11-21, live site):

  * The jobs category is ``/c/emplois`` on ``lexpress-petites-annonces.mu``,
    server-rendered, paginated with ``?page={n}`` (~12 ads/page).
  * Ad URLs are ``/annonce/<YYYYMMDD>-<digits>``.
  * ``<title>`` is site-wide (``"L'Express Petites Annonces"``); the job title
    is the ``<h1>``.
  * Dates are French long form (``16 novembre 2026``).
  * Breadcrumb and ``Localisation:`` share the class ``text-sm text-gray-500``;
    the breadcrumb is the one containing ``>``.
  * There is no employer field and no salary field; salary is prose in the body.
  * Contact emails are Cloudflare-obfuscated.

No test touches the network.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from job_market_intel.cleaning.lexpress_mu_cleaner import (
    LexpressMuCleaner,
    _map_employment_type,
)
from job_market_intel.scrapers.lexpress_mu.client import LexpressMuClient
from job_market_intel.scrapers.lexpress_mu.config import LexpressMuSettings
from job_market_intel.scrapers.lexpress_mu.exceptions import (
    LexpressMuParseError,
    LexpressMuResponseError,
)
from job_market_intel.scrapers.lexpress_mu.models import RawLexpressMuJob
from job_market_intel.scrapers.lexpress_mu.parser import (
    LexpressMuParser,
    _decode_cf_email,
    _extract_salary,
    _parse_french_date,
    parse_detail,
)
from job_market_intel.validation.lexpress_mu_validator import (
    LexpressMuBatchValidator,
    LexpressMuValidationSettings,
)

TODAY = date(2026, 11, 16)

#: The real Cloudflare value from the live ad; decodes to contact@bluelife.mu.
CF_EMAIL = "177478796376746357757b62727b7e7172397a62"

LISTING = """<!DOCTYPE html><html><body>
<main>
  <a href="/annonce/20261116-1794825510">Pool Attendant</a>
  <a href="https://lexpress-petites-annonces.mu/annonce/20261013-1791885496">Nounou</a>
  <a href="/annonce/20260929-1790664479">Receptionist</a>
  <a href="/c/emplois?page=2">Suivant</a>
</main>
</body></html>"""

DETAIL = f"""<!DOCTYPE html><html><head>
<title>L'Express Petites Annonces</title>
</head><body>
<main>
  <h1 class="text-2xl font-bold w-[65%]">Pool Attendant - Azuri (Roches Noires)</h1>
  <p class="text-xs lg:text-md font-bold">Ref: 20261116-1794825510</p>
  <p class="text-sm text-gray-500">Emplois  &gt; Full-Time <span class="font-bold"> </span></p>
  <p class="mt-1 text-xs text-gray-500">16 novembre 2026</p>
  <div>
    <p class="text-lg">WE ARE RECRUITING - POOL ATTENDANT

Azuri is looking for an experienced and motivated Pool Attendant to join its
Pool Team. Salary Package: MUR 27,000 - MUR 35,000 per month.

Key Responsibilities:
- Carry out daily cleaning and maintenance of swimming pools.
- Monitor water quality, pH levels and pool chemical balance.

Send your CV to <a class="__cf_email__" data-cfemail="{CF_EMAIL}"
href="/cdn-cgi/l/email-protection">[email protected]</a> or call 57440057.</p>
    <p class="text-sm text-gray-500">Localisation: Roches Noires</p>
    <div class="mt-2 font-semibold flex flex-row gap-2 items-center">
      <div><svg></svg></div>
      <div>57440057</div>
    </div>
  </div>
  <a href="https://www.google.com/maps/search/Azuri/@-20.09,57.70,17z?hl=en" target="_blank">
    <img alt="Google Maps" src="/images/google-maps.png"/>
  </a>
</main>
</body></html>"""

DETAIL_FR = """<!DOCTYPE html><html><head>
<title>L'Express Petites Annonces</title>
</head><body>
<main>
  <h1>Nounou fiable avec reference moka</h1>
  <p class="text-xs lg:text-md font-bold">Ref: 20261013-1791885496</p>
  <p class="text-sm text-gray-500">Emplois  &gt; Part-Time</p>
  <p class="mt-1 text-xs text-gray-500">13 octobre 2026</p>
  <p class="text-lg">Je cherche une nounou fiable avec de l'experience dans le
domaine pour ma fille, du lundi au vendredi de 12h30 a 17h30 a Moka.
Possibilite de teletravail partiel.</p>
  <p class="text-sm text-gray-500">Localisation: Moka</p>
</main>
</body></html>"""


def _raw(**overrides) -> RawLexpressMuJob:
    base = {
        "source_job_id": "20261116-1794825510",
        "title": "Pool Attendant - Azuri (Roches Noires)",
        "company_name": "Azuri",
        "location": "Roches Noires",
        "country": "Mauritius",
        "description": "We are recruiting a pool attendant. " * 10,
        "employment_type": "Full-Time",
        "category": "Emplois",
        "salary_text": "MUR 27,000 - MUR 35,000",
        "salary_min": 27000.0,
        "salary_max": 35000.0,
        "salary_period": "monthly",
        "posted_date": TODAY,
        "reference": "20261116-1794825510",
        "phone": "57440057",
        "contact_emails": ["contact@bluelife.mu"],
        "remote_phrase": None,
        "url": "https://lexpress-petites-annonces.mu/annonce/20261116-1794825510",
        "listing_page": 1,
        "raw": {"company_source": "maps"},
    }
    base.update(overrides)
    return RawLexpressMuJob(**base)


class TestListingLinks:
    def test_pagination_uses_page_and_page_one_is_bare(self):
        client = LexpressMuClient(LexpressMuSettings())
        assert client.listing_url(1) == "https://lexpress-petites-annonces.mu/c/emplois"
        assert client.listing_url(2) == ("https://lexpress-petites-annonces.mu/c/emplois?page=2")

    def test_only_annonce_tokens_become_ads(self):
        client = LexpressMuClient(LexpressMuSettings())
        client._fetch = lambda url: LISTING
        links = client.fetch_listing_page(1)
        assert set(links) == {
            "20261116-1794825510",
            "20261013-1791885496",
            "20260929-1790664479",
        }
        assert "page=2" not in " ".join(links.values())

    def test_empty_discovery_raises_rather_than_returning_nothing(self):
        client = LexpressMuClient(LexpressMuSettings(max_pages=1))
        client._fetch = lambda url: "<html><body>maintenance</body></html>"
        with pytest.raises(LexpressMuResponseError, match="markup changed"):
            client.discover_detail_paths()

    def test_records_can_be_fetched_without_detail_pages(self):
        client = LexpressMuClient(LexpressMuSettings(fetch_description=False))
        client.discover_detail_paths = lambda: (
            {"20261116-1794825510": {"path": "/annonce/20261116-1794825510", "page": 1}},
            {},
        )
        records, failures = client.fetch_raw_jobs()
        assert failures == {}
        assert records[0]["job_id"] == "20261116-1794825510"
        assert records[0]["html"] is None


class TestTitleTrap:
    def test_title_comes_from_h1_not_the_site_title_tag(self):
        job = parse_detail("20261116-1794825510", DETAIL)
        assert job.title == "Pool Attendant - Azuri (Roches Noires)"
        assert "Petites Annonces" not in job.title

    def test_a_page_with_no_h1_is_an_error_not_a_title(self):
        with pytest.raises(LexpressMuParseError, match="no title"):
            parse_detail("x", "<html><body><main><p>gone</p></main></body></html>")


class TestBreadcrumb:
    def test_employment_type_is_the_tail_after_the_chevron(self):
        job = parse_detail("20261116-1794825510", DETAIL)
        assert job.category == "Emplois"
        assert job.employment_type == "Full-Time"

    def test_the_localisation_line_is_not_the_breadcrumb(self):
        job = parse_detail("20261116-1794825510", DETAIL)
        assert job.location == "Roches Noires"
        assert job.employment_type == "Full-Time"


class TestFrenchDates:
    def test_a_french_long_date_is_read(self):
        assert _parse_french_date("16 novembre 2026") == date(2026, 11, 16)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1 janvier 2026", date(2026, 1, 1)),
            ("28 fevrier 2026", date(2026, 2, 28)),
            ("1 aout 2026", date(2026, 8, 1)),
            ("31 decembre 2026", date(2026, 12, 31)),
        ],
    )
    def test_month_names_including_accents_folded(self, raw, expected):
        assert _parse_french_date(raw) == expected

    @pytest.mark.parametrize("bad", ["", None, "16 november 2026", "40 novembre 2026"])
    def test_unreadable_dates_are_none(self, bad):
        assert _parse_french_date(bad) is None

    def test_the_posting_date_not_a_sidebar_date(self):
        html = DETAIL.replace(
            '<p class="mt-1 text-xs text-gray-500">16 novembre 2026</p>',
            '<p class="mt-1 text-xs text-gray-500">16 novembre 2026</p>'
            '<div class="text-xs uppercase text-[11px]">19 mars 2026</div>',
        )
        assert parse_detail("20261116-1794825510", html).posted_date == date(2026, 11, 16)

    def test_a_french_ad_dates_as_well(self):
        assert parse_detail("20261013-1791885496", DETAIL_FR).posted_date == date(2026, 10, 13)


class TestSalary:
    def test_a_range_is_split_into_min_and_max(self):
        text, low, high, period, assumed = _extract_salary(
            "Salary Package: MUR 27,000 - MUR 35,000 per month."
        )
        assert (low, high) == (27000.0, 35000.0)
        assert period == "monthly"
        assert assumed is False

    def test_a_single_figure_is_min_equal_max_and_monthly_by_default(self):
        text, low, high, period, assumed = _extract_salary("Salary: MUR 25,000")
        assert (low, high) == (25000.0, 25000.0)
        assert period == "monthly"
        assert assumed is True

    def test_rs_is_accepted(self):
        text, low, high, period, assumed = _extract_salary("Rs 20,000 per day")
        assert (low, high) == (20000.0, 20000.0)
        assert period == "daily"

    def test_no_salary_is_none_not_a_guess(self):
        assert _extract_salary("No figure in this body at all.")[1:3] == (None, None)

    def test_the_parsed_ad_carries_the_salary(self):
        job = parse_detail("20261116-1794825510", DETAIL)
        assert job.salary_min == 27000.0
        assert job.salary_max == 35000.0
        assert job.salary_period == "monthly"


class TestCompany:
    def test_the_maps_query_is_the_employer_when_present(self):
        job = parse_detail("20261116-1794825510", DETAIL)
        assert job.company_name == "Azuri"
        assert job.raw["company_source"] == "maps"

    def test_a_body_heuristic_is_used_when_there_is_no_maps_link(self):
        html = (
            "<html><body><main>"
            "<h1>Pool Attendant</h1>"
            '<p class="text-lg">Azuri is looking for an experienced Pool Attendant '
            "to join its team.</p>"
            "</main></body></html>"
        )
        job = parse_detail("x", html)
        assert job.company_name == "Azuri"
        assert job.raw["company_source"] == "body"

    def test_no_employer_signal_falls_back_to_unknown(self):
        html = (
            "<html><body><main>"
            "<h1>Housemaid</h1>"
            '<p class="text-lg">Hello all, looking for work.</p>'
            "</main></body></html>"
        )
        job = parse_detail("x", html)
        assert job.company_name == "Unknown employer"
        assert job.raw["company_source"] == "none"

    @pytest.mark.parametrize(
        "body",
        [
            "We are looking for a motivated candidate to join us.",
            "If you are looking for an exciting new role, apply now.",
            "We are urgently seeking a housekeeper for a villa.",
            "La compagnie ZELECT WORK LTD recrute du personnel.",
        ],
    )
    def test_prose_is_never_stored_as_an_employer(self, body):
        html = f'<html><body><main><h1>Post</h1><p class="text-lg">{body}</p></main></body></html>'
        job = parse_detail("x", html)
        assert job.company_name == "Unknown employer"
        assert job.raw["company_source"] == "none"


class TestRemote:
    def test_a_french_remote_phrase_is_recorded(self):
        job = parse_detail("20261013-1791885496", DETAIL_FR)
        assert job.remote_phrase == "teletravail"

    def test_a_plain_ad_has_no_remote_phrase(self):
        job = parse_detail("20261116-1794825510", DETAIL)
        assert job.remote_phrase is None


class TestEmails:
    def test_the_cloudflare_email_is_decoded_for_audit(self):
        assert _decode_cf_email(CF_EMAIL) == "contact@bluelife.mu"

    def test_the_ad_collects_the_decoded_email(self):
        job = parse_detail("20261116-1794825510", DETAIL)
        assert job.contact_emails == ["contact@bluelife.mu"]

    def test_a_missing_or_bad_value_is_none(self):
        assert _decode_cf_email(None) is None
        assert _decode_cf_email("zz") is None


class TestPhone:
    def test_the_phone_is_captured(self):
        assert parse_detail("20261116-1794825510", DETAIL).phone == "57440057"


class TestCleaner:
    def test_the_contract_is_fully_populated(self):
        cleaned = LexpressMuCleaner().clean_job(_raw())
        assert cleaned.job_title == "Pool Attendant - Azuri (Roches Noires)"
        assert cleaned.company_name == "Azuri"
        assert cleaned.location_cleaned == "Roches Noires"
        assert cleaned.posting_date == datetime(2026, 11, 16)
        assert cleaned.currency_iso_code == "MUR"
        assert cleaned.pay_period == "monthly"
        assert cleaned.employment_type_code == "full_time"

    def test_no_salary_is_invented(self):
        cleaned = LexpressMuCleaner().clean_job(
            _raw(salary_text=None, salary_min=None, salary_max=None, salary_period=None)
        )
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False
        assert cleaned.pay_period == "yearly"
        assert cleaned.raw_payload["salary_published"] is False

    def test_a_locationless_ad_falls_back_to_the_country(self):
        cleaned = LexpressMuCleaner().clean_job(_raw(location=None))
        assert cleaned.location_cleaned == "Mauritius"

    def test_an_unknown_employer_is_not_an_empty_string(self):
        cleaned = LexpressMuCleaner().clean_job(_raw(company_name=""))
        assert cleaned.company_name == "Unknown employer"

    def test_remote_is_recorded_but_never_mapped_to_a_guess(self):
        cleaned = LexpressMuCleaner().clean_job(_raw(remote_phrase="teletravail"))
        assert cleaned.remote_work_type_code is None
        assert cleaned.raw_payload["remote_phrase"] == "teletravail"

    def test_quality_score_rewards_a_readable_ad(self):
        good = LexpressMuCleaner().clean_job(_raw())
        thin = LexpressMuCleaner().clean_job(
            _raw(description="x", salary_min=None, salary_max=None, location=None)
        )
        assert good.data_quality_score > thin.data_quality_score

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Full-Time", "full_time"),
            ("Full Time", "full_time"),
            ("Part-Time", "part_time"),
            ("Part Time", "part_time"),
            ("Contract", "contract"),
            ("Temporary", "temporary"),
            ("Internship", "internship"),
            ("", None),
            (None, None),
        ],
    )
    def test_employment_type_mapping(self, value, expected):
        assert _map_employment_type(value) == expected


class TestValidator:
    def _jobs(self, n: int) -> list[RawLexpressMuJob]:
        return [_raw(source_job_id=f"2026110{i}-17948255{i:02d}") for i in range(n)]

    def test_a_normal_batch_passes(self):
        jobs = self._jobs(30)
        report = LexpressMuBatchValidator().validate(jobs, jobs)
        assert report.passed, report.issues

    def test_a_thin_batch_fails(self):
        jobs = self._jobs(3)
        report = LexpressMuBatchValidator().validate(jobs, jobs)
        assert not report.passed
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_unknown_employers_do_not_fail_the_batch(self):
        jobs = [_raw(source_job_id=f"id-{i}", company_name="Unknown employer") for i in range(30)]
        report = LexpressMuBatchValidator().validate(jobs, jobs)
        assert report.passed, "a classifieds board of anonymous ads is a property of the board"
        assert report.missing_field_rates["company_name"] == 1.0

    def test_duplicate_ids_are_flagged(self):
        jobs = self._jobs(30)
        jobs.append(jobs[0])
        assert LexpressMuBatchValidator().validate(jobs, jobs).duplicate_source_job_ids

    def test_thresholds_are_configurable(self):
        validator = LexpressMuBatchValidator(LexpressMuValidationSettings(min_expected_jobs=2))
        jobs = self._jobs(3)
        assert validator.validate(jobs, jobs).passed


class TestParserClass:
    def test_parse_many_collects_issues_without_crashing(self):
        parser = LexpressMuParser()
        records = [
            {"job_id": "20261116-1794825510", "html": DETAIL},
            {"job_id": "bad", "html": "<html><body><main>nothing</main></body></html>"},
        ]
        parsed, issues = parser.parse_many(records)
        assert len(parsed) == 1
        assert parsed[0].source_job_id == "20261116-1794825510"
        assert len(issues) == 1


class TestSettings:
    def test_defaults(self):
        settings = LexpressMuSettings()
        assert settings.base_url == "https://lexpress-petites-annonces.mu"
        assert settings.listing_path == "/c/emplois"
        assert settings.max_pages == 12

    def test_overrides(self):
        settings = LexpressMuSettings(max_jobs_per_run=10, max_pages=2)
        assert settings.max_jobs_per_run == 10
        assert settings.max_pages == 2

    def test_rejects_nonsense(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LexpressMuSettings(inter_request_delay_seconds=-1.0)
