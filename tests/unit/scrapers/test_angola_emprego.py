"""Unit tests for the Angola Emprego scraper.

Each test pins a fact measured on the live site on 2026-10-18, which is how every
other scraper's tests here is written. The one that would have cost the whole
batch if guessed:

  1. **``employmentType`` is a LIST** (``["FULL_TIME"]``), not the bare string
     every other source here emits. A cleaner written for them calls
     ``.strip()``, raises ``AttributeError``, and -- because ``clean_jobs``
     catches per record -- drops **every** posting while the run still reports
     success. This is a silent, total loss, so it gets its own tests.
  2. **``identifier`` is a ``PropertyValue`` whose ``value`` is a slug string**
     -- neither an int nor the numeric URL suffix. Some URL slugs end ``-4818``
     and others do not, so the URL slug is the key.
  3. **No ``baseSalary``** on any measured posting, so salary coverage is zero
     by nature of the board, not by parser failure.

Also pinned: ``?page=`` is compliant while ``/vagas?q=`` is robots-disallowed,
and the dates carry a timezone offset.

Run with:  uv run pytest tests/unit/scrapers/test_angola_emprego.py -q
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from job_market_intel.cleaning.angola_emprego_cleaner import (
    AngolaEmpregoCleaner,
    _map_country,
    _map_employment_type,
)
from job_market_intel.scrapers.angola_emprego.client import _JOB_LINK, AngolaEmpregoClient
from job_market_intel.scrapers.angola_emprego.config import AngolaEmpregoSettings
from job_market_intel.scrapers.angola_emprego.exceptions import (
    AngolaEmpregoParseError,
    AngolaEmpregoResponseError,
)
from job_market_intel.scrapers.angola_emprego.parser import (
    AngolaEmpregoParser,
    _extract_employment_type,
    _extract_identifier,
    _extract_location,
    _parse_date,
)

#: Trimmed verbatim from a live detail page fetched 2026-10-18
#: (/vagas/grande-oportunidade-para-coordenador-industrial-4818).
POSTING = {
    "@context": "https://schema.org/",
    "@type": "JobPosting",
    "title": "Grande oportunidade para Coordenador Industrial",
    "description": "Sobre a Vaga\nA QGMI CONSTRUCCIONES E INFRAESTRUCTURAS GLOBALES S.L. (SU) – "
    "SUCURSAL EM ANGOLA, empresa de Direito angolano.",
    "datePosted": "2026-10-17T08:30:47+00:00",
    "validThrough": "2026-12-17T08:30:47+00:00",
    # THE TRAP: a list, not a bare string.
    "employmentType": ["FULL_TIME"],
    "hiringOrganization": {
        "@type": "Organization",
        "name": "QGMI Construcciones e Infraestructuras Globales S.L. (SU) – Sucursal em Angola",
        "logo": "https://angolaemprego.com/img/logo.png",
    },
    # THE TRAP: a slug string, not an int.
    "identifier": {
        "@type": "PropertyValue",
        "name": "QGMI Construcciones e Infraestructuras Globales S.L. (SU) – Sucursal em Angola",
        "value": "grande-oportunidade-para-coordenador-industrial-4818",
    },
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "Mavinga, Cuando",
            "addressRegion": "Mavinga",
            "addressCountry": "Angola",
        },
    },
}


def detail_html(posting: dict | None = None) -> str:
    body = POSTING if posting is None else posting
    return (
        f'<html><head><script type="application/ld+json">{json.dumps(body)}</script>'
        "</head><body></body></html>"
    )


# ====================================================================== links


class TestListingLinks:
    def test_link_regex_takes_the_slug(self) -> None:
        html = '<a href="/vagas/grande-oportunidade-para-coordenador-industrial-4818">x</a>'
        found = [m.group(1) for m in _JOB_LINK.finditer(html)]
        assert found == ["/vagas/grande-oportunidade-para-coordenador-industrial-4818"]

    def test_the_measured_href_form_is_absolute(self) -> None:
        """THE trap, and it cost a CI run.

        Measured 2026-10-18: **all 15** listing hrefs are absolute and **zero**
        are relative. The first version of this scraper anchored on
        ``href="/vagas/..."`` and matched nothing on a board serving 15 postings
        a page -- CI run 39032134903 reported "0 link(s)" on every page.

        The local probe missed it because it resolved links with ``urljoin``,
        which normalizes both forms, so the probe and the implementation
        disagreed about what the site emits. This test pins the raw form.
        """
        html = (
            '<a href="https://angolaemprego.com/vagas/'
            'grande-oportunidade-para-coordenador-industrial-4818">x</a>'
        )
        found = [m.group(1) for m in _JOB_LINK.finditer(html)]
        assert found == ["/vagas/grande-oportunidade-para-coordenador-industrial-4818"]

    def test_both_forms_are_accepted(self) -> None:
        """Defensive: a board that switches to relative hrefs must not break it."""
        slug = "/vagas/grande-oportunidade-para-head-of-geology"
        for prefix in ("", "https://angolaemprego.com", "https://www.angolaemprego.com"):
            html = f'<a href="{prefix}{slug}">x</a>'
            assert [m.group(1) for m in _JOB_LINK.finditer(html)] == [slug]

    def test_a_real_listing_snippet_excludes_the_bare_listing_path(self) -> None:
        """The exact shape of the first three hrefs on the live listing."""
        html = (
            '<a href="https://angolaemprego.com/vagas">Todas</a>'
            '<a href="https://angolaemprego.com/vagas/grande-oportunidade-para-coordenador-'
            'industrial-4818">1</a>'
            '<a href="https://angolaemprego.com/vagas/grande-oportunidade-para-motoristas">2</a>'
        )
        found = [m.group(1) for m in _JOB_LINK.finditer(html)]
        assert "/vagas" not in found, "the bare listing path must not be treated as a posting"
        assert len(found) == 2

    def test_a_slug_without_a_numeric_suffix_still_matches(self) -> None:
        """Measured: some slugs end -4818 and others do not."""
        html = '<a href="/vagas/grande-oportunidade-para-head-of-geology">x</a>'
        assert [m.group(1) for m in _JOB_LINK.finditer(html)] == [
            "/vagas/grande-oportunidade-para-head-of-geology"
        ]

    def test_the_bare_listing_path_is_not_a_posting(self) -> None:
        assert list(_JOB_LINK.finditer('<a href="/vagas/">Todas</a>')) == []

    def test_listing_url_omits_the_query_on_page_one(self) -> None:
        client = AngolaEmpregoClient(AngolaEmpregoSettings())
        assert client.listing_url(1) == "https://angolaemprego.com/vagas"
        assert client.listing_url(2) == "https://angolaemprego.com/vagas?page=2"

    def test_pagination_uses_page_not_a_disallowed_filter(self) -> None:
        """robots.txt disallows /vagas?q=, /vagas?location=, /vagas?category=."""
        url = AngolaEmpregoClient(AngolaEmpregoSettings()).listing_url(3)
        assert url.endswith("?page=3")
        for disallowed in ("?q=", "?location=", "?category="):
            assert disallowed not in url

    def test_empty_discovery_raises_rather_than_returning_nothing(self) -> None:
        client = AngolaEmpregoClient(AngolaEmpregoSettings(max_pages=1))
        client._fetch = lambda url: "<html><body>nothing</body></html>"  # type: ignore[method-assign]
        with pytest.raises(AngolaEmpregoResponseError, match="markup changed"):
            client.discover_detail_paths()

    def test_a_repeated_page_is_not_counted_twice(self) -> None:
        body = (
            '<a href="/vagas/grande-oportunidade-para-coordenador-industrial-4818">a</a>'
            '<a href="/vagas/grande-oportunidade-para-head-of-geology">b</a>'
        )
        client = AngolaEmpregoClient(
            AngolaEmpregoSettings(max_pages=2, inter_request_delay_seconds=0.0)
        )
        client._fetch = lambda url: body  # type: ignore[method-assign]
        found, failures = client.discover_detail_paths()
        assert failures == {}
        assert len(found) == 2


# ====================================================================== dates


class TestDates:
    @pytest.mark.parametrize(
        "raw", ["2026-10-17T08:30:47+00:00", "2026-10-17T08:30:47Z", "2026-10-17"]
    )
    def test_iso_with_a_timezone_offset(self, raw: str) -> None:
        assert _parse_date(raw) == date(2026, 10, 17)

    @pytest.mark.parametrize("raw", [None, "", "null", "not a date"])
    def test_junk_is_none_not_an_exception(self, raw) -> None:
        assert _parse_date(raw) is None


# ============================================================== employmentType


class TestEmploymentTypeIsAList:
    """THE trap. A string-only cleaner drops the entire batch silently."""

    def test_the_measured_list_shape_is_read(self) -> None:
        assert _extract_employment_type(["FULL_TIME"]) == ["FULL_TIME"]

    def test_a_bare_string_is_also_accepted(self) -> None:
        """Defensive: the board could change this without notice."""
        assert _extract_employment_type("FULL_TIME") == ["FULL_TIME"]

    def test_multiple_values_are_all_kept(self) -> None:
        assert _extract_employment_type(["FULL_TIME", "PART_TIME"]) == ["FULL_TIME", "PART_TIME"]

    def test_absent_and_empty_are_none(self) -> None:
        assert _extract_employment_type(None) is None
        assert _extract_employment_type([]) is None
        assert _extract_employment_type([""]) is None


class TestEmploymentTypeMapping:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (["FULL_TIME"], "full_time"),
            (["PART_TIME"], "part_time"),
            (["CONTRACT"], "contract"),
            (["TEMPORARY"], "temporary"),
            (["INTERN"], "internship"),
        ],
    )
    def test_schema_vocabulary_maps_to_database_codes(self, raw, expected) -> None:
        assert _map_employment_type(raw) == expected

    def test_a_bare_string_still_maps(self) -> None:
        assert _map_employment_type("FULL_TIME") == "full_time"

    def test_the_first_recognized_value_wins(self) -> None:
        """One code per job; inventing a precedence would be a guess."""
        assert _map_employment_type(["PER_DIEM", "FULL_TIME"]) == "full_time"

    def test_unrecognized_is_none(self) -> None:
        assert _map_employment_type(["NEW"]) is None
        assert _map_employment_type(None) is None


# =================================================================== identifier


class TestIdentifier:
    def test_the_slug_string_is_read(self) -> None:
        assert (
            _extract_identifier(POSTING) == "grande-oportunidade-para-coordenador-industrial-4818"
        )

    def test_an_int_value_would_also_be_stringified(self) -> None:
        assert _extract_identifier({"identifier": {"value": 4818}}) == "4818"

    def test_name_only_property_value_falls_back_to_the_name(self) -> None:
        assert _extract_identifier({"identifier": {"name": "ACME"}}) == "ACME"

    def test_absent_identifier_is_none(self) -> None:
        assert _extract_identifier({}) is None


# ==================================================================== location


class TestLocation:
    def test_city_and_region_are_both_read(self) -> None:
        label, country, city, region = _extract_location(POSTING)
        assert country == "Angola"
        assert city == "Mavinga, Cuando"
        assert region == "Mavinga"

    def test_duplicate_city_and_region_collapse_in_the_label(self) -> None:
        ld = {"jobLocation": {"address": {"addressLocality": "Luanda", "addressRegion": "Luanda"}}}
        label, _, _, _ = _extract_location(ld)
        assert label == "Luanda"

    def test_missing_location_is_not_an_error(self) -> None:
        assert _extract_location({}) == (None, None, None, None)


class TestCountryNormalization:
    def test_angola_is_normalized_to_the_iso_code(self) -> None:
        assert _map_country("Angola") == "AO"

    def test_an_iso_code_passes_through(self) -> None:
        assert _map_country("AO") == "AO"

    def test_an_unmapped_name_is_none_rather_than_a_guess(self) -> None:
        assert _map_country("Wakanda") is None
        assert _map_country(None) is None


# ====================================================================== parser


class TestParser:
    def test_a_full_posting_is_parsed(self) -> None:
        job = AngolaEmpregoParser().parse(
            "grande-oportunidade-para-coordenador-industrial-4818",
            detail_html(),
            url="https://angolaemprego.com/vagas/grande-oportunidade-para-coordenador-industrial-4818",
        )
        assert job.title.startswith("Grande oportunidade")
        assert job.company_name.startswith("QGMI")
        assert job.company_logo_url is not None
        assert job.employment_type == ["FULL_TIME"]
        assert job.posted_date == date(2026, 10, 17)
        assert job.closing_date == date(2026, 12, 17)
        assert job.country == "Angola"

    def test_employment_type_lands_as_a_list(self) -> None:
        """Asserted on the model, not just the helper: the model is the contract."""
        job = AngolaEmpregoParser().parse("x", detail_html())
        assert isinstance(job.employment_type, list)

    def test_no_salary_is_recorded_rather_than_assumed(self) -> None:
        job = AngolaEmpregoParser().parse("x", detail_html())
        assert job.raw["has_base_salary"] is False
        assert job.salary_min is None and job.salary_max is None

    def test_the_url_slug_is_the_key_not_the_identifier(self) -> None:
        job = AngolaEmpregoParser().parse("url-slug", detail_html())
        assert job.source_job_id == "url-slug"
        assert job.raw["identifier_value"] != "url-slug"

    def test_no_title_raises(self) -> None:
        with pytest.raises(AngolaEmpregoParseError, match="no title"):
            AngolaEmpregoParser().parse("1", detail_html({}))

    def test_parse_many_collects_failures_rather_than_raising(self) -> None:
        records = [{"job_id": "1", "html": detail_html()}, {"job_id": "2", "html": detail_html({})}]
        jobs, issues = AngolaEmpregoParser().parse_many(records)
        assert [j.source_job_id for j in jobs] == ["1"]
        assert len(issues) == 1


# ====================================================================== cleaner


class TestCleaner:
    def _job(self, **kw):
        return (
            AngolaEmpregoParser()
            .parse("grande-oportunidade-para-coordenador-industrial-4818", detail_html())
            .model_copy(update=kw)
        )

    def test_the_list_does_not_crash_the_cleaner(self) -> None:
        """The whole point of the employmentType trap test."""
        cleaned = AngolaEmpregoCleaner().clean_job(self._job())
        assert cleaned.employment_type_code == "full_time"

    def test_no_salary_is_ever_claimed(self) -> None:
        cleaned = AngolaEmpregoCleaner().clean_job(self._job())
        assert cleaned.salary_min is None
        assert cleaned.salary_disclosed is False
        assert cleaned.raw_payload["salary_published"] is False

    def test_country_is_recorded_as_an_iso_code(self) -> None:
        payload = AngolaEmpregoCleaner().clean_job(self._job()).raw_payload
        assert payload["country_iso"] == "AO"
        assert payload["country_raw"] == "Angola"

    def test_country_only_location_is_kept(self) -> None:
        job = self._job(location=None, country="Angola")
        assert AngolaEmpregoCleaner().clean_job(job).location_cleaned == "AO"

    def test_skills_are_empty_because_the_board_has_none(self) -> None:
        assert AngolaEmpregoCleaner().clean_job(self._job()).skills == []

    def test_language_is_recorded_as_portuguese(self) -> None:
        assert AngolaEmpregoCleaner().clean_job(self._job()).raw_payload["language"] == "pt"

    def test_company_whitespace_is_collapsed(self) -> None:
        job = self._job(company_name="QGMI  Construcciones\n e Infra")
        assert AngolaEmpregoCleaner().clean_job(job).company_name == "QGMI Construcciones e Infra"

    def test_quality_score_is_a_fraction(self) -> None:
        s = AngolaEmpregoCleaner().clean_job(self._job()).data_quality_score
        assert 0.0 <= s <= 1.0


# ==================================================================== validator


class TestValidator:
    def _report(self, n: int = 15, posting: dict | None = None):
        from job_market_intel.validation.angola_emprego_validator import (
            AngolaEmpregoBatchValidator,
        )

        parser = AngolaEmpregoParser()
        raw = [{"job_id": f"slug-{i}", "html": detail_html(posting)} for i in range(n)]
        parsed = [parser.parse(r["job_id"], r["html"]) for r in raw]
        return AngolaEmpregoBatchValidator().validate(raw, parsed)

    def test_a_full_batch_passes(self) -> None:
        assert self._report().passed

    def test_an_empty_description_is_censused(self) -> None:
        report = self._report(posting={**POSTING, "description": ""})
        assert report.missing_field_rates.get("description") == 1.0

    def test_absent_location_is_counted_but_not_fatal(self) -> None:
        payload = {k: v for k, v in POSTING.items() if k != "jobLocation"}
        report = self._report(posting=payload)
        assert report.passed
        assert report.missing_field_rates.get("location") == 1.0

    def test_a_thin_batch_does_fail(self) -> None:
        assert not self._report(n=3).passed


# ==================================================================== settings


class TestSettings:
    def test_defaults(self) -> None:
        s = AngolaEmpregoSettings()
        assert s.base_url == "https://angolaemprego.com"
        assert s.listing_path == "/vagas"
        assert s.max_jobs_per_run == 120

    def test_overrides_are_honoured(self) -> None:
        s = AngolaEmpregoSettings(max_pages=3, max_jobs_per_run=25)
        assert (s.max_pages, s.max_jobs_per_run) == (3, 25)

    def test_settings_reject_nonsense_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AngolaEmpregoSettings(inter_request_delay_seconds=-1.0)
        with pytest.raises(ValidationError):
            AngolaEmpregoSettings(max_jobs_per_run=0)
