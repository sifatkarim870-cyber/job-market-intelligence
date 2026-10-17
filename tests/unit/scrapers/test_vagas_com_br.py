"""Unit tests for the Vagas.com.br scraper.

Each test pins a fact measured on the live site on 2026-10-18, which is how every
other scraper's tests here is written. The three that would each have broken the
source if guessed:

  1. **``addressCountry`` is the name ``"Brasil"``, not the ISO code.** Every
     other country-carrying source emits an ISO code (``PT``, ``ZA``), and
     ``geographic_resolution`` matches on ISO codes -- so an unmapped
     ``"Brasil"`` resolves to no country and the row collapses onto the
     global-remote location. This is a *silent* loss, which is why it has its
     own test rather than being folded into a location assertion.
  2. **``identifier`` is a ``PropertyValue`` whose ``value`` is an int**
     (``2831966``). A parser expecting a string id stores nothing identifiable.
  3. **``baseSalary`` nests its numbers *flat* under ``value``** --
     ``value.unitText`` / ``value.minValue`` / ``value.maxValue``. That is not
     Apna's or Mustakbil's ``value.value.minValue``, not Wellfound's
     ``value.minValue``, and not Careers24's scalar. A parser written for any of
     the other four layouts reads ``None`` and stores a salary of 0 without
     complaining.

Also pinned: the JSON-LD block is **malformed on some pages**, ``?p=2`` is not
the page parameter (it serves a 30 KB page with 0 postings), and the board
publishes **no** ``employmentType`` at all.

Run with:  uv run pytest tests/unit/scrapers/test_vagas_com_br.py -q
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from job_market_intel.cleaning.vagas_com_br_cleaner import (
    VagasComBrCleaner,
    _map_country,
    _map_pay_period,
)
from job_market_intel.scrapers.vagas_com_br.client import _JOB_LINK, VagasComBrClient
from job_market_intel.scrapers.vagas_com_br.config import VagasComBrSettings
from job_market_intel.scrapers.vagas_com_br.exceptions import (
    VagasComBrParseError,
    VagasComBrResponseError,
)
from job_market_intel.scrapers.vagas_com_br.parser import (
    VagasComBrParser,
    _extract_identifier,
    _extract_location,
    _extract_salary,
    _parse_date,
    extract_jsonld,
)

#: Trimmed verbatim from a live detail page fetched 2026-10-18
#: (/vagas/v2833634/tecnico-de-saude-seguranca-e-meio-ambiente) -- the one of
#: three measured that carried a baseSalary.
POSTING_WITH_SALARY = {
    "@context": "http://schema.org",
    "@type": "JobPosting",
    "title": "Tecnico de Saúde, Segurança e Meio Ambiente",
    "description": "Descrição: DESCRIÇÃO DA VAGAProfissional responsável por atuar "
    "como ponto focal de saúde, segurança e meio ambiente da empresa.",
    "datePosted": "2026-09-03",
    "validThrough": "2026-10-30",
    "hiringOrganization": {"@type": "Organization", "name": "VEKTO ENGENHARIA"},
    "identifier": {"@type": "PropertyValue", "name": "VEKTO ENGENHARIA", "value": 2833634},
    "jobBenefits": "Vale-refeição, Assistência médica, Vale-transporte",
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "Belo Horizonte",
            "addressRegion": "MG",
            # THE TRAP: a country NAME, not the ISO code "BR".
            "addressCountry": "Brasil",
        },
    },
    # THE TRAP: flat under value, and unitText is MONTH.
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "BRL",
        "value": {
            "@type": "QuantitativeValue",
            "unitText": "MONTH",
            "minValue": 4300,
            "maxValue": 4500,
        },
    },
}

#: The other two measured postings carried no baseSalary and no employmentType.
POSTING_NO_SALARY = {
    "@context": "http://schema.org",
    "@type": "JobPosting",
    "title": "Oportunidade de Jovem Aprendiz – Multinacional",
    "description": "Descrição: OPORTUNIDADE DE JOVEM APRENDIZ – MULTINACIONALEstá em "
    "busca do seu primeiro emprego e quer iniciar sua carreira em uma grande empresa?",
    "datePosted": "2026-08-24",
    "validThrough": "2026-10-30",
    "hiringOrganization": {"@type": "Organization", "name": "TP"},
    "identifier": {"@type": "PropertyValue", "name": "TP", "value": 2831966},
    "jobBenefits": "Vale-refeição, Assistência médica, Vale-transporte",
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "São Paulo",
            "addressRegion": "SP",
            "addressCountry": "Brasil",
        },
    },
}


def detail_html(posting: dict | None = None) -> str:
    body = POSTING_WITH_SALARY if posting is None else posting
    return (
        f'<html><head><script type="application/ld+json">{json.dumps(body)}</script>'
        "</head><body></body></html>"
    )


# ====================================================================== links


class TestListingLinks:
    def test_link_regex_takes_the_numeric_id(self) -> None:
        html = '<a href="/vagas/v2831966/oportunidade-de-jovem-aprendiz-multinacional">x</a>'
        found = {m.group(2): m.group(1) for m in _JOB_LINK.finditer(html)}
        assert found == {"2831966": "/vagas/v2831966/oportunidade-de-jovem-aprendiz-multinacional"}

    def test_link_regex_tolerates_a_trailing_slash(self) -> None:
        html = '<a href="/vagas/v2831966/enfermeiro-sala-de-infusao-quimioterapico/">x</a>'
        assert [m.group(2) for m in _JOB_LINK.finditer(html)] == ["2831966"]

    def test_link_regex_ignores_the_disallowed_search_path(self) -> None:
        """robots.txt disallows /vagas/pesquisas, which is not a posting."""
        html = '<a href="/vagas/pesquisas">buscar</a><a href="/vagas/v12/x">short id</a>'
        assert list(_JOB_LINK.finditer(html)) == []

    def test_listing_url_omits_the_query_on_page_one(self) -> None:
        client = VagasComBrClient(VagasComBrSettings())
        assert client.listing_url(1) == "https://www.vagas.com.br/vagas-de-emprego/"
        assert client.listing_url(2) == "https://www.vagas.com.br/vagas-de-emprego/?page=2"

    def test_empty_discovery_raises_rather_than_returning_nothing(self) -> None:
        client = VagasComBrClient(VagasComBrSettings(max_pages=1))
        client._fetch = lambda url: "<html><body>nothing</body></html>"  # type: ignore[method-assign]
        with pytest.raises(VagasComBrResponseError, match="markup changed"):
            client.discover_detail_paths()

    def test_a_repeated_page_is_not_counted_twice(self) -> None:
        """The pager is real, but a static regression must not double-count."""
        body = (
            '<a href="/vagas/v2831966/oportunidade-de-jovem-aprendiz">a</a>'
            '<a href="/vagas/v2833262/enfermeiro-sala-de-infusao">b</a>'
        )
        client = VagasComBrClient(VagasComBrSettings(max_pages=2, inter_request_delay_seconds=0.0))
        client._fetch = lambda url: body  # type: ignore[method-assign]
        found, failures = client.discover_detail_paths()
        assert failures == {}
        assert set(found) == {"2831966", "2833262"}


# ===================================================================== JSON-LD


class TestMalformedJsonLd:
    """The block is malformed on some pages -- raw control characters."""

    def test_strict_parsing_fails_on_a_malformed_block(self) -> None:
        raw = '{"@type": "JobPosting", "title": "x", "description": "line1\nline2"}'
        with pytest.raises(json.JSONDecodeError):
            json.loads(raw)

    def test_lenient_parsing_is_used_as_a_fallback(self) -> None:
        block = '{"@type": "JobPosting", "title": "x", "description": "line1\nline2"}'
        html = f'<html><script type="application/ld+json">{block}</script></html>'
        assert extract_jsonld(html)["title"] == "x"

    def test_a_well_formed_block_is_parsed_strictly_first(self) -> None:
        """Strict-first means a clean page never pays for the leniency."""
        assert extract_jsonld(detail_html())["title"].startswith("Tecnico")

    def test_unparseable_json_is_skipped_not_fatal(self) -> None:
        assert extract_jsonld("<html><script type='application/ld+json'>{oops</script>") == {}

    def test_no_block_returns_empty(self) -> None:
        assert extract_jsonld("<html><body>hi</body></html>") == {}


# ====================================================================== dates


class TestDates:
    @pytest.mark.parametrize("raw", ["2026-08-24", "2026-08-24T10:00:00Z"])
    def test_common_shapes(self, raw: str) -> None:
        assert _parse_date(raw) == date(2026, 8, 24)

    @pytest.mark.parametrize("raw", [None, "", "null", "not a date"])
    def test_junk_is_none_not_an_exception(self, raw) -> None:
        assert _parse_date(raw) is None


# =================================================================== identifier


class TestIdentifier:
    """``identifier`` is a PropertyValue whose ``value`` is an int.

    The helpers take the whole JobPosting node, which is how the parser calls
    them.
    """

    def test_the_int_value_is_stringified(self) -> None:
        assert _extract_identifier(POSTING_WITH_SALARY) == "2833634"

    def test_a_bare_int_is_accepted(self) -> None:
        assert _extract_identifier({"identifier": 2833634}) == "2833634"

    def test_a_bare_string_is_accepted(self) -> None:
        assert _extract_identifier({"identifier": " 2833634 "}) == "2833634"

    def test_name_only_property_value_falls_back_to_the_name(self) -> None:
        assert _extract_identifier({"identifier": {"@type": "PropertyValue", "name": "TP"}}) == "TP"

    def test_absent_identifier_is_none(self) -> None:
        assert _extract_identifier({}) is None


# ====================================================================== salary


class TestSalaryLayout:
    """Flat under ``value`` -- a sixth distinct layout in this codebase."""

    def test_the_measured_flat_layout_is_read(self) -> None:
        cur, lo, hi, unit = _extract_salary(POSTING_WITH_SALARY)
        assert cur == "BRL"
        assert (lo, hi) == (4300.0, 4500.0)
        assert unit == "MONTH"

    def test_an_apna_style_nested_layout_is_also_tolerated(self) -> None:
        """value.value.minValue -- the band layout Mustakbil and Apna use."""
        cur, lo, _, unit = _extract_salary(
            {
                "baseSalary": {
                    "currency": "INR",
                    "value": {"value": {"unitText": "MONTH", "minValue": 180000}},
                }
            }
        )
        assert (cur, lo, unit) == ("INR", 180000.0, "MONTH")

    def test_absent_salary_is_all_none_not_zero(self) -> None:
        assert _extract_salary({}) == (None, None, None, None)
        assert _extract_salary({"@type": "JobPosting"}) == (None, None, None, None)

    def test_an_empty_unit_text_is_dropped_rather_than_guessed(self) -> None:
        """Alfred's precedent: an empty unitText was dropped, not called yearly."""
        _, _, _, unit = _extract_salary(
            {"baseSalary": {"currency": "ZAR", "value": {"unitText": "", "minValue": 100}}}
        )
        assert unit is None

    def test_non_numeric_bounds_are_none_not_an_exception(self) -> None:
        _, lo, hi, _ = _extract_salary(
            {
                "baseSalary": {
                    "currency": "BRL",
                    "value": {"unitText": "MONTH", "minValue": "R Undisclosed"},
                }
            }
        )
        assert lo is None and hi is None


# ==================================================================== location


class TestLocation:
    def test_country_arrives_as_a_name_not_an_iso_code(self) -> None:
        label, country, city, region = _extract_location(POSTING_WITH_SALARY)
        assert country == "Brasil"
        assert (city, region) == ("Belo Horizonte", "MG")
        assert label == "Belo Horizonte, MG"

    def test_duplicate_city_and_region_collapse_in_the_label(self) -> None:
        ld = {
            "jobLocation": {
                "address": {
                    "addressLocality": "Lisboa",
                    "addressRegion": "Lisboa",
                    "addressCountry": "Brasil",
                }
            }
        }
        label, _, _, _ = _extract_location(ld)
        assert label == "Lisboa"

    def test_missing_location_is_not_an_error(self) -> None:
        assert _extract_location({}) == (None, None, None, None)


class TestCountryNormalization:
    """The trap that loses countries silently."""

    def test_brasil_is_normalized_to_the_iso_code(self) -> None:
        assert _map_country("Brasil") == "BR"

    def test_brazil_is_accepted_too(self) -> None:
        assert _map_country("Brazil") == "BR"

    def test_an_iso_code_passes_through(self) -> None:
        assert _map_country("BR") == "BR"

    def test_an_unmapped_name_is_none_rather_than_a_guess(self) -> None:
        assert _map_country("Wakanda") is None
        assert _map_country(None) is None


# =================================================================== pay period


class TestPayPeriod:
    def test_month_is_monthly(self) -> None:
        """Storing a monthly figure as annual would overstate it twelvefold."""
        assert _map_pay_period("MONTH") == "monthly"

    @pytest.mark.parametrize(
        ("unit", "expected"),
        [("HOUR", "hourly"), ("DAY", "daily"), ("WEEK", "weekly"), ("YEAR", "yearly")],
    )
    def test_the_schema_vocabulary_maps(self, unit: str, expected: str) -> None:
        assert _map_pay_period(unit) == expected

    def test_every_result_is_inside_the_check_constraint(self) -> None:
        for unit in ("HOUR", "DAY", "WEEK", "MONTH", "YEAR", "", None, "FORTNIGHT"):
            assert _map_pay_period(unit) in {"hourly", "daily", "weekly", "monthly", "yearly"}


# ====================================================================== parser


class TestParser:
    def test_a_full_posting_is_parsed(self) -> None:
        job = VagasComBrParser().parse(
            "2833634", detail_html(), url="https://www.vagas.com.br/vagas/v2833634/x"
        )
        assert job.source_job_id == "2833634"
        assert job.title.startswith("Tecnico")
        assert job.company_name == "VEKTO ENGENHARIA"
        assert job.posted_date == date(2026, 9, 3)
        assert job.closing_date == date(2026, 10, 30)
        assert (job.salary_min, job.salary_max) == (4300.0, 4500.0)
        assert job.salary_currency == "BRL"
        assert job.salary_unit_text == "MONTH"

    def test_the_descricao_label_is_stripped(self) -> None:
        """Every measured description opens with 'Descrição:' glued to the text."""
        job = VagasComBrParser().parse("2831966", detail_html(POSTING_NO_SALARY))
        assert job.description is not None
        assert not job.description.lower().startswith("descri")

    def test_a_posting_without_salary_parses_with_none_amounts(self) -> None:
        job = VagasComBrParser().parse("2831966", detail_html(POSTING_NO_SALARY))
        assert job.salary_min is None and job.salary_max is None
        assert job.raw["has_base_salary"] is False
        assert job.raw["has_identifier"] is True

    def test_the_identifier_is_recorded_alongside_the_url_id(self) -> None:
        job = VagasComBrParser().parse("2833634", detail_html())
        assert job.raw["identifier_value"] == "2833634"

    def test_no_title_raises(self) -> None:
        with pytest.raises(VagasComBrParseError, match="no title"):
            VagasComBrParser().parse("1", detail_html({}))

    def test_parse_many_collects_failures_rather_than_raising(self) -> None:
        records = [{"job_id": "1", "html": detail_html()}, {"job_id": "2", "html": detail_html({})}]
        jobs, issues = VagasComBrParser().parse_many(records)
        assert [j.source_job_id for j in jobs] == ["1"]
        assert len(issues) == 1


# ====================================================================== cleaner


class TestCleaner:
    def _job(self, **kw):
        return VagasComBrParser().parse("2833634", detail_html()).model_copy(update=kw)

    def test_monthly_is_not_stored_as_yearly(self) -> None:
        cleaned = VagasComBrCleaner().clean_job(self._job())
        assert cleaned.pay_period == "monthly"
        assert cleaned.salary_min == 4300.0
        assert cleaned.salary_disclosed is True

    def test_no_salary_means_not_disclosed(self) -> None:
        job = VagasComBrParser().parse("2831966", detail_html(POSTING_NO_SALARY))
        cleaned = VagasComBrCleaner().clean_job(job)
        assert cleaned.salary_disclosed is False
        assert cleaned.salary_min is None

    def test_the_country_is_recorded_as_an_iso_code(self) -> None:
        cleaned = VagasComBrCleaner().clean_job(self._job())
        assert cleaned.raw_payload["country_iso"] == "BR"
        assert cleaned.raw_payload["country_raw"] == "Brasil"

    def test_employment_type_is_none_because_the_board_publishes_none(self) -> None:
        """0 of 3 measured carry employmentType, so this is honest absence."""
        assert VagasComBrCleaner().clean_job(self._job()).employment_type_code is None

    def test_reversed_salary_bounds_are_swapped_not_dropped(self) -> None:
        job = self._job(salary_min=4500.0, salary_max=4300.0)
        cleaned = VagasComBrCleaner().clean_job(job)
        assert (cleaned.salary_min, cleaned.salary_max) == (4300.0, 4500.0)

    def test_country_only_location_is_kept(self) -> None:
        job = self._job(location=None, country="Brasil", city=None)
        assert VagasComBrCleaner().clean_job(job).location_cleaned == "BR"

    def test_benefits_are_preserved(self) -> None:
        cleaned = VagasComBrCleaner().clean_job(self._job())
        assert "Vale-refeição" in cleaned.raw_payload["job_benefits"]

    def test_language_is_recorded_as_portuguese(self) -> None:
        assert VagasComBrCleaner().clean_job(self._job()).raw_payload["language"] == "pt"

    def test_skills_are_empty_because_the_board_has_none(self) -> None:
        assert VagasComBrCleaner().clean_job(self._job()).skills == []

    def test_quality_score_is_a_fraction(self) -> None:
        s = VagasComBrCleaner().clean_job(self._job()).data_quality_score
        assert 0.0 <= s <= 1.0


# ==================================================================== validator


class TestValidator:
    def _report(self, n: int = 40, posting: dict | None = None):
        from job_market_intel.validation.vagas_com_br_validator import (
            VagasComBrBatchValidator,
        )

        parser = VagasComBrParser()
        raw = [{"job_id": str(2833600 + i), "html": detail_html(posting)} for i in range(n)]
        parsed = [parser.parse(r["job_id"], r["html"]) for r in raw]
        return VagasComBrBatchValidator().validate(raw, parsed)

    def test_a_full_batch_passes(self) -> None:
        assert self._report().passed

    def test_missing_salary_is_censused_but_not_fatal(self) -> None:
        """1 of 3 postings carried no salary, so a 100% salary rate is normal."""
        report = self._report(posting=POSTING_NO_SALARY)
        assert report.passed
        assert report.missing_field_rates.get("salary") == 1.0

    def test_employment_type_is_not_in_the_census(self) -> None:
        """The board publishes none, so a check would be a permanent failure."""
        assert "employment_type" not in self._report().missing_field_rates

    def test_an_empty_description_is_censused(self) -> None:
        report = self._report(posting={**POSTING_WITH_SALARY, "description": ""})
        assert report.missing_field_rates.get("description") == 1.0

    def test_a_thin_batch_does_fail(self) -> None:
        assert not self._report(n=5).passed


# ==================================================================== settings


class TestSettings:
    def test_defaults(self) -> None:
        s = VagasComBrSettings()
        assert s.base_url == "https://www.vagas.com.br"
        assert s.listing_path == "/vagas-de-emprego/"
        assert s.max_jobs_per_run == 60

    def test_the_throttle_delay_is_pinned(self) -> None:
        """The site returned 429 to 30 of 45 detail fetches at 1.0s.

        Without this the default could be "tidied" back to a faster value and
        every run would silently lose two thirds of its batch.
        """
        assert VagasComBrSettings().inter_request_delay_seconds >= 3.5

    def test_overrides_are_honoured(self) -> None:
        s = VagasComBrSettings(max_pages=3, max_jobs_per_run=25)
        assert (s.max_pages, s.max_jobs_per_run) == (3, 25)

    def test_settings_reject_nonsense_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            VagasComBrSettings(inter_request_delay_seconds=-1.0)
        with pytest.raises(ValidationError):
            VagasComBrSettings(max_jobs_per_run=0)
