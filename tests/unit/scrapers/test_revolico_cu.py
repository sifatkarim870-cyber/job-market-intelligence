"""Unit tests for the Revolico (Cuba) scraper.

Pinned measured facts (2026-11-21, live site):

  * The employers' board is
    ``/search?category=empleos_&subcategory=empleos-ofertas-de-empleo``
    (the sibling ``empleos-busco-empleo`` holds job-seekers); it paginates
    with ``?page={n}`` (~100 ads/page).
  * Ad URLs are ``/item/<slug>-<id>``; ``<id>`` is the trailing number and the
    stable ``source_job_id``.
  * Each page embeds its data in ``<script id="__NEXT_DATA__">``; the ads are
    the ``AdType:*`` entries of ``props.pageProps.__APOLLO_STATE__``.
  * Listing ads carry no description; the detail page carries the full ad.
  * ``ProvinceType``/``MunicipalityType`` refs carry ``name`` (e.g. "La
    Habana" / "La Lisa").
  * There is no original posting date (only ``updatedOnByUser``), no employer
    field (``name`` is the poster), and ``price`` is unreliable (absent on 55
    of 102 sampled ads; many of the rest carry a placeholder ``1``).

No test touches the network.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from job_market_intel.cleaning.revolico_cu_cleaner import RevolicoCuCleaner
from job_market_intel.scrapers.revolico_cu.client import (
    RevolicoCuClient,
    apollo_state,
    extract_next_data,
)
from job_market_intel.scrapers.revolico_cu.config import RevolicoCuSettings
from job_market_intel.scrapers.revolico_cu.exceptions import (
    RevolicoCuParseError,
    RevolicoCuResponseError,
)
from job_market_intel.scrapers.revolico_cu.models import RawRevolicoCuJob
from job_market_intel.scrapers.revolico_cu.parser import (
    RevolicoCuParser,
    _detect_remote,
    _extract_phone,
    _parse_iso_date,
    parse_detail,
)
from job_market_intel.validation.revolico_cu_validator import (
    RevolicoCuBatchValidator,
    RevolicoCuValidationSettings,
)

TODAY = date(2026, 11, 20)


def _page(state: dict, title: str = "Revolico  - Anuncios clasificados en Cuba") -> str:
    payload = {
        "props": {"pageProps": {"__APOLLO_STATE__": state, "ssrCountry": "BD"}},
        "page": "/search",
        "query": {},
    }
    return (
        "<!DOCTYPE html><html><head><title>" + title + "</title></head><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload, ensure_ascii=False)
        + "</script></body></html>"
    )


LISTING_STATE = {
    "AdType:55794055": {
        "__typename": "AdType",
        "id": "55794055",
        "title": "Se busca: Custodio de La Finca",
        "price": 1000,
        "currency": "CUP",
        "permalink": "/item/se-busca-custodio-de-la-finca-55794055",
        "provinceId": "1",
        "municipalityId": "43",
        "updatedOnToOrder": "2026-11-20T20:51:46.137Z",
    },
    "AdType:58975165": {
        "__typename": "AdType",
        "id": "58975165",
        "title": "SE BUSCAN GESTORES DE VENTA ONLINE",
        "price": 1,
        "currency": "USD",
        "permalink": "/item/se-buscan-gestores-de-venta-online-58975165",
    },
    "CategoryType:1301": {
        "__typename": "CategoryType",
        "id": "1301",
        "title": "Ofertas de Empleo",
        "slug": "empleos-ofertas-de-empleo",
    },
}
LISTING = _page(LISTING_STATE)

DESCRIPTION = (
    "Se busca: Custodio de La Finca\n_\nLa persona de edad 40+, educada, en "
    "buena forma fisica, buena presencia, con experiencia laboral y servicio "
    "militar. Se ofrece alojamiento y alimentacion. Interesados llamar."
)
DETAIL_STATE = {
    "AdType:55794055": {
        "__typename": "AdType",
        "id": "55794055",
        "title": "Se busca: Custodio de La Finca",
        "shortDescription": "Se busca: Custodio de La Finca",
        "description": DESCRIPTION,
        "price": 1000,
        "currency": "CUP",
        "name": "Yury",
        "status": "PUBLISHED",
        "contactInfo": "PHONE",
        "updatedOnByUser": "2026-11-20T20:51:46.137Z",
        "isPromoted": False,
        "isSold": False,
        "province": {"__ref": "ProvinceType:1"},
        "municipality": {"__ref": "MunicipalityType:43"},
        "subcategory": {"__ref": "CategoryType:1301"},
        "viewCount": 944,
        "permalink": "/item/se-busca-custodio-de-la-finca-55794055",
        "phoneInfo": {
            "__typename": "AdPhoneInfo",
            "firstPhone": {
                "__typename": "Phone",
                "prefix": "+53",
                "number": "53310760",
            },
        },
    },
    "ProvinceType:1": {
        "__typename": "ProvinceType",
        "id": "1",
        "slug": "la-habana",
        "name": "La Habana",
    },
    "MunicipalityType:43": {
        "__typename": "MunicipalityType",
        "id": "43",
        "slug": "la-lisa",
        "name": "La Lisa",
    },
    "CategoryType:1301": {
        "__typename": "CategoryType",
        "id": "1301",
        "title": "Ofertas de Empleo",
        "slug": "empleos-ofertas-de-empleo",
    },
}
DETAIL = _page(
    DETAIL_STATE,
    title="Se busca: Custodio de La Finca en La Lisa, La Habana, Cuba - Revolico",
)


def _raw(**overrides) -> RawRevolicoCuJob:
    base = {
        "source_job_id": "55794055",
        "title": "Se busca: Custodio de La Finca",
        "company_name": "Unknown employer",
        "poster_name": "Yury",
        "location": "La Lisa, La Habana",
        "province": "La Habana",
        "municipality": "La Lisa",
        "country": "Cuba",
        "description": DESCRIPTION,
        "category": "Ofertas de Empleo",
        "subcategory_slug": "empleos-ofertas-de-empleo",
        "price": 1000.0,
        "price_currency": "CUP",
        "posted_date": TODAY,
        "updated_on": "2026-11-20T20:51:46.137Z",
        "phone": "+5353310760",
        "remote_phrase": None,
        "url": "https://www.revolico.com/item/se-busca-custodio-de-la-finca-55794055",
        "listing_page": 1,
        "raw": {
            "date_source": "updatedOnByUser (last bump; the board has no original posting date)"
        },
    }
    base.update(overrides)
    return RawRevolicoCuJob(**base)


class TestListingDiscovery:
    def test_pagination_uses_page_and_page_one_is_bare(self):
        client = RevolicoCuClient(RevolicoCuSettings())
        assert client.listing_url(1) == (
            "https://www.revolico.com/search"
            "?category=empleos_&subcategory=empleos-ofertas-de-empleo"
        )
        assert client.listing_url(2) == (
            "https://www.revolico.com/search"
            "?category=empleos_&subcategory=empleos-ofertas-de-empleo&page=2"
        )

    def test_only_adtype_entries_become_ads(self):
        client = RevolicoCuClient(RevolicoCuSettings())
        client._fetch = lambda url: LISTING
        links = client.fetch_listing_page(1)
        assert set(links) == {"55794055", "58975165"}
        assert links["55794055"] == "/item/se-busca-custodio-de-la-finca-55794055"

    def test_empty_discovery_raises_rather_than_returning_nothing(self):
        client = RevolicoCuClient(RevolicoCuSettings(max_pages=1))
        client._fetch = lambda url: _page({})
        with pytest.raises(RevolicoCuResponseError, match="markup changed"):
            client.discover_detail_paths()

    def test_records_can_be_fetched_without_detail_pages(self):
        client = RevolicoCuClient(RevolicoCuSettings(fetch_detail=False))
        client.discover_detail_paths = lambda: (
            {"55794055": {"path": "/item/x-55794055", "page": 1}},
            {},
        )
        records, failures = client.fetch_raw_jobs()
        assert failures == {}
        assert records[0]["job_id"] == "55794055"
        assert records[0]["html"] is None


class TestNextDataHelpers:
    def test_next_data_is_extracted(self):
        assert extract_next_data(LISTING)["props"]["pageProps"]["ssrCountry"] == "BD"

    def test_apollo_state_is_returned(self):
        assert "AdType:55794055" in apollo_state(DETAIL)

    @pytest.mark.parametrize(
        "bad", ["", "<html></html>", "<script id='__NEXT_DATA__'>{oops</script>"]
    )
    def test_missing_or_invalid_next_data_is_none_never_a_crash(self, bad):
        assert extract_next_data(bad) is None
        assert apollo_state(bad) == {}


class TestDetailParsing:
    def test_the_full_ad_is_parsed(self):
        job = parse_detail("55794055", DETAIL)
        assert job.source_job_id == "55794055"
        assert job.title == "Se busca: Custodio de La Finca"
        assert job.description.startswith("Se busca: Custodio de La Finca")
        assert job.province == "La Habana"
        assert job.municipality == "La Lisa"
        assert job.location == "La Lisa, La Habana"
        assert job.category == "Ofertas de Empleo"
        assert job.subcategory_slug == "empleos-ofertas-de-empleo"

    def test_the_employer_is_never_the_poster(self):
        job = parse_detail("55794055", DETAIL)
        assert job.company_name == "Unknown employer"
        assert job.poster_name == "Yury"

    def test_the_price_is_kept_for_audit_but_is_not_a_salary(self):
        job = parse_detail("55794055", DETAIL)
        assert job.price == 1000.0
        assert job.price_currency == "CUP"
        assert not hasattr(job, "salary_min")

    def test_the_phone_is_assembled_from_prefix_and_number(self):
        assert parse_detail("55794055", DETAIL).phone == "+5353310760"

    def test_a_page_with_no_ad_is_an_error_not_a_blank_job(self):
        with pytest.raises(RevolicoCuParseError, match="no AdType"):
            parse_detail("55794055", _page({"CategoryType:1301": {"id": "1301"}}))

    def test_a_page_with_an_unparsable_island_is_the_same_error(self):
        with pytest.raises(RevolicoCuParseError, match="markup changed"):
            parse_detail("55794055", "<html><body>gone</body></html>")

    def test_an_empty_title_is_an_error(self):
        html = _page({"AdType:x": {"__typename": "AdType", "id": "x", "title": "  "}})
        with pytest.raises(RevolicoCuParseError, match="empty title"):
            parse_detail("x", html)

    def test_multi_ad_page_resolves_the_requested_ad(self):
        state = dict(DETAIL_STATE)
        state["AdType:58975165"] = {
            "__typename": "AdType",
            "id": "58975165",
            "title": "Otro anuncio",
            "description": "otro",
        }
        html = _page(state)
        assert parse_detail("58975165", html).title == "Otro anuncio"
        assert parse_detail("55794055", html).title == "Se busca: Custodio de La Finca"

    def test_a_locationless_ad_falls_back_to_the_country(self):
        html = _page(
            {
                "AdType:1": {
                    "__typename": "AdType",
                    "id": "1",
                    "title": "Trabajo",
                    "description": "Sin provincia ni municipio declarados.",
                }
            }
        )
        job = parse_detail("1", html)
        assert job.location == "Cuba"
        assert job.country == "Cuba"


class TestDates:
    def test_the_updated_on_date_is_read(self):
        assert parse_detail("55794055", DETAIL).posted_date == TODAY

    def test_the_last_bump_is_flagged_as_the_date_source(self):
        job = parse_detail("55794055", DETAIL)
        assert "updatedOnByUser" in job.raw["date_source"]
        assert job.updated_on == "2026-11-20T20:51:46.137Z"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2026-11-20T20:51:46.137Z", date(2026, 11, 20)),
            ("2026-01-02", date(2026, 1, 2)),
        ],
    )
    def test_iso_timestamps_are_read(self, raw, expected):
        assert _parse_iso_date(raw) == expected

    @pytest.mark.parametrize("bad", ["", None, "20 noviembre 2026", "2026-13-40"])
    def test_unreadable_dates_are_none(self, bad):
        assert _parse_iso_date(bad) is None

    def test_a_missing_timestamp_is_none_not_today(self):
        html = _page(
            {
                "AdType:1": {
                    "__typename": "AdType",
                    "id": "1",
                    "title": "Trabajo",
                    "description": "Sin fecha.",
                }
            }
        )
        assert parse_detail("1", html).posted_date is None


class TestRemote:
    def test_a_spanish_remote_phrase_is_recorded(self):
        assert _detect_remote("Se ofrece trabajo remoto desde casa.") == "trabajo remoto"

    def test_teletrabajo_is_recorded(self):
        assert _detect_remote("Modalidad teletrabajo.") == "teletrabajo"

    def test_a_plain_ad_has_no_remote_phrase(self):
        assert _detect_remote("Se busca custodio para finca.") is None

    def test_the_parsed_ad_records_it(self):
        html = _page(
            {
                "AdType:1": {
                    "__typename": "AdType",
                    "id": "1",
                    "title": "Programador",
                    "description": "Se ofrece programador en modalidad teletrabajo.",
                }
            }
        )
        assert parse_detail("1", html).remote_phrase == "teletrabajo"


class TestPhone:
    def test_a_missing_phone_info_is_none(self):
        assert _extract_phone({"id": "1"}) is None

    def test_the_second_phone_is_used_when_the_first_is_absent(self):
        ad = {"phoneInfo": {"secondPhone": {"prefix": "+53", "number": "55551234"}}}
        assert _extract_phone(ad) == "+5355551234"


class TestCleaner:
    def test_the_contract_is_fully_populated(self):
        cleaned = RevolicoCuCleaner().clean_job(_raw())
        assert cleaned.job_title == "Se busca: Custodio de La Finca"
        assert cleaned.company_name == "Unknown employer"
        assert cleaned.location_cleaned == "La Lisa, La Habana"
        assert cleaned.posting_date == datetime(2026, 11, 20)
        assert cleaned.currency_iso_code == "CUP"

    def test_no_salary_is_ever_invented(self):
        cleaned = RevolicoCuCleaner().clean_job(_raw())
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False
        assert cleaned.pay_period == "yearly"
        assert cleaned.raw_payload["salary_published"] is False
        assert cleaned.raw_payload["price_raw"] == 1000.0
        assert cleaned.raw_payload["price_is_reliable"] is False

    def test_a_locationless_ad_falls_back_to_the_country(self):
        assert RevolicoCuCleaner().clean_job(_raw(location=None)).location_cleaned == "Cuba"

    def test_an_unknown_employer_is_not_an_empty_string(self):
        assert RevolicoCuCleaner().clean_job(_raw(company_name="")).company_name == (
            "Unknown employer"
        )

    def test_no_employment_type_is_guessed(self):
        assert RevolicoCuCleaner().clean_job(_raw()).employment_type_code is None

    def test_remote_is_recorded_but_never_mapped_to_a_guess(self):
        cleaned = RevolicoCuCleaner().clean_job(_raw(remote_phrase="teletrabajo"))
        assert cleaned.remote_work_type_code is None
        assert cleaned.raw_payload["remote_phrase"] == "teletrabajo"

    def test_the_poster_is_kept_in_the_payload(self):
        assert RevolicoCuCleaner().clean_job(_raw()).raw_payload["poster_name"] == "Yury"

    def test_quality_score_rewards_a_readable_ad(self):
        good = RevolicoCuCleaner().clean_job(_raw())
        thin = RevolicoCuCleaner().clean_job(
            _raw(description="x", location=None, category=None, phone=None, posted_date=None)
        )
        assert good.data_quality_score > thin.data_quality_score


class TestValidator:
    def _jobs(self, n: int) -> list[RawRevolicoCuJob]:
        return [_raw(source_job_id=f"550000{i:02d}") for i in range(n)]

    def test_a_normal_batch_passes(self):
        jobs = self._jobs(30)
        report = RevolicoCuBatchValidator().validate(jobs, jobs)
        assert report.passed, report.issues

    def test_a_thin_batch_fails(self):
        jobs = self._jobs(3)
        report = RevolicoCuBatchValidator().validate(jobs, jobs)
        assert not report.passed
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_unknown_employers_do_not_fail_the_batch(self):
        jobs = [_raw(source_job_id=f"id-{i}") for i in range(30)]
        report = RevolicoCuBatchValidator().validate(jobs, jobs)
        assert report.passed, "a classifieds board of anonymous ads is a property of the board"
        assert report.missing_field_rates["company_name"] == 1.0

    def test_duplicate_ids_are_flagged(self):
        jobs = self._jobs(30)
        jobs.append(jobs[0])
        assert RevolicoCuBatchValidator().validate(jobs, jobs).duplicate_source_job_ids

    def test_thresholds_are_configurable(self):
        validator = RevolicoCuBatchValidator(RevolicoCuValidationSettings(min_expected_jobs=2))
        jobs = self._jobs(3)
        assert validator.validate(jobs, jobs).passed


class TestParserClass:
    def test_parse_many_collects_issues_without_crashing(self):
        parser = RevolicoCuParser()
        records = [
            {"job_id": "55794055", "html": DETAIL},
            {"job_id": "bad", "html": _page({"CategoryType:1301": {"id": "1301"}})},
        ]
        parsed, issues = parser.parse_many(records)
        assert len(parsed) == 1
        assert parsed[0].source_job_id == "55794055"
        assert len(issues) == 1


class TestSettings:
    def test_defaults(self):
        settings = RevolicoCuSettings()
        assert settings.base_url == "https://www.revolico.com"
        assert settings.search_path == "/search"
        assert settings.category == "empleos_"
        assert settings.subcategory == "empleos-ofertas-de-empleo"
        assert settings.max_pages == 6
        assert settings.max_jobs_per_run == 200

    def test_overrides(self):
        settings = RevolicoCuSettings(max_jobs_per_run=10, max_pages=2)
        assert settings.max_jobs_per_run == 10
        assert settings.max_pages == 2

    def test_rejects_nonsense(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RevolicoCuSettings(inter_request_delay_seconds=-1.0)
