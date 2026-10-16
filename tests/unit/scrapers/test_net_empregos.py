"""Unit tests for the Net-Empregos scraper.

Each test pins a fact measured on the live site on 2026-10-16, which is how every
other scraper's tests here is written. The ones that would each have broken the
source if guessed:

  1. **The JSON-LD is malformed.** The ``description`` string contains raw
     newlines, which makes ``json.loads`` raise ``Invalid control character``.
     A strict parser reads nothing at all from every page -- which is exactly
     what the first probe reported, before the fix was found. The fix is
     ``json.loads(block, strict=False)``.
  2. **There is no ``identifier``** (0 of 3 postings), so the URL id is the only
     stable key the board offers. A parser that expects one stores nothing
     identifiable and re-runs insert duplicates forever.
  3. **There is no ``baseSalary``** (0 of 3). Net-Empregos publishes no salary,
     so ``salary_disclosed`` is always ``False`` and no ``pay_period`` is
     claimed about a figure that does not exist.
  4. ``addressCountry`` is the ISO code ``"PT"``, and ``datePosted`` /
     ``validThrough`` are formatted ``"2026-10-16 21:47 UTC"``.
  5. Descriptions run **3400+** characters, so the 100-character gate used
     everywhere else here is comfortable.

Run with:  uv run pytest tests/unit/scrapers/test_net_empregos.py -q
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from job_market_intel.cleaning.net_empregos_cleaner import (
    NetEmpregosCleaner,
    _map_employment_type,
)
from job_market_intel.scrapers.net_empregos.client import _JOB_LINK, NetEmpregosClient
from job_market_intel.scrapers.net_empregos.config import NetEmpregosSettings
from job_market_intel.scrapers.net_empregos.exceptions import (
    NetEmpregosParseError,
    NetEmpregosResponseError,
)
from job_market_intel.scrapers.net_empregos.parser import (
    NetEmpregosParser,
    _extract_location,
    _parse_date,
    extract_jsonld,
)

#: Trimmed verbatim from a live detail page fetched 2026-10-16
#: (/jobs/16131249/especialista-de-apoio-ao-cliente-servicos-bancarios/).
#: The description contains raw newlines, which is the trap.
POSTING = {
    "@context": "http://schema.org",
    "@type": "JobPosting",
    "title": "Especialista de Apoio ao Cliente - Serviços Bancários",
    "description": "<b>Anúncio de Emprego: Especialistas de Apoio ao Cliente"
    " para Projeto Bancário Internacional em Lisboa</b>\n<BR>\n<BR>A Workster "
    "está a colaborar com um prestador de serviços de experiência do cliente de "
    "renome para recrutar Especialistas de Apoio ao Cliente para um projeto "
    "bancário internacional em Lisboa.",
    "datePosted": "2026-10-16 21:47 UTC",
    "validThrough": "2026-11-15 21:47 UTC",
    "employmentType": "FULL_TIME",
    "hiringOrganization": {
        "@type": "Organization",
        "name": "Workster",
        "logo": "https://www.net-empregos.com/img/logos/logo_novo_sqare_new.png",
    },
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "Lisboa",
            "addressRegion": "Lisboa",
            "addressCountry": "PT",
            "postalCode": "Lisboa",
            "streetAddress": "Lisboa",
        },
    },
    "industry": "Call Center / Help Desk",
}


def detail_html(posting: dict | None = None) -> str:
    body = POSTING if posting is None else posting
    return (
        f'<html><head><script type="application/ld+json">{json.dumps(body)}</script>'
        "</head><body></body></html>"
    )


# ====================================================================== links


class TestListingLinks:
    def test_link_regex_takes_the_numeric_id(self) -> None:
        """The detail path has no /jobs/ prefix -- measured, not assumed.

        The first implementation required ``/jobs/`` in the path and matched
        zero links on a board serving 18 per page, which is exactly the kind of
        silent total loss the regex tests exist to catch.
        """
        html = '<a href="/16131249/especialista-de-apoio-ao-cliente-servicos-bancarios/">x</a>'
        # group(1) is the id; the full href is in the match text.
        found = {m.group(1): m.group(0).split('"')[1] for m in _JOB_LINK.finditer(html)}
        assert found == {
            "16131249": "/16131249/especialista-de-apoio-ao-cliente-servicos-bancarios/"
        }

    def test_link_regex_ignores_non_job_paths(self) -> None:
        html = (
            '<a href="/jobs">All jobs</a>'
            '<a href="/12345/short/">x</a>'  # id too short
            '<a href="/empresa/1234567890/x">Company</a>'
        )
        assert list(_JOB_LINK.finditer(html)) == []

    def test_listing_url_omits_the_query_on_page_one(self) -> None:
        client = NetEmpregosClient(NetEmpregosSettings())
        assert client.listing_url(1) == "https://www.net-empregos.com/jobs"
        assert client.listing_url(3) == "https://www.net-empregos.com/jobs?page=3"

    def test_empty_discovery_raises_rather_than_returning_nothing(self) -> None:
        client = NetEmpregosClient(NetEmpregosSettings(max_pages=1))
        client._fetch = lambda url: "<html><body>nothing</body></html>"  # type: ignore[method-assign]
        with pytest.raises(NetEmpregosResponseError, match="markup changed"):
            client.discover_detail_paths()

    def test_a_repeated_page_is_not_counted_twice(self) -> None:
        """First listing wins, so a posting reachable from two pages is fetched once."""
        body = (
            '<a href="/16131249/especialista-de-apoio/">a</a>'
            '<a href="/16131250/carpinteiros-de-cofragem/">b</a>'
        )
        client = NetEmpregosClient(
            NetEmpregosSettings(
                max_pages=2,
                inter_request_delay_seconds=0.0,
            )
        )
        # Both pages return the same body, so the second page adds nothing.
        client._fetch = lambda url: body  # type: ignore[method-assign]
        found, failures = client.discover_detail_paths()
        assert failures == {}
        assert set(found) == {"16131249", "16131250"}


# ====================================================================== JSON-LD


class TestMalformedJsonLd:
    """The description contains raw newlines. This is the trap."""

    def test_strict_parsing_fails_on_the_real_payload(self) -> None:
        """A strict parser reads nothing at all from every page.

        The site's raw block has literal newlines inside the description
        string. ``json.dumps`` of a Python dict would escape them, so this
        builds the malformed text the way the site actually emits it.
        """
        raw = json.dumps(POSTING, ensure_ascii=False).replace("\\n", "\n")
        with pytest.raises(json.JSONDecodeError):
            json.loads(raw)

    def test_lenient_parsing_succeeds(self) -> None:
        assert extract_jsonld(detail_html())["title"].startswith("Especialista")

    def test_the_description_survives_with_its_newlines(self) -> None:
        """The newlines are content, not structure -- they must not be lost."""
        desc = extract_jsonld(detail_html())["description"]
        assert "\n" in desc
        assert "Workster" in desc

    def test_malformed_json_is_skipped_not_fatal(self) -> None:
        assert extract_jsonld("<html><script type='application/ld+json'>{oops</script>") == {}

    def test_no_block_returns_empty(self) -> None:
        assert extract_jsonld("<html><body>hi</body></html>") == {}


# ======================================================================= dates


class TestDates:
    @pytest.mark.parametrize("raw", ["2026-10-16 21:47 UTC", "2026-10-16", "2026-10-16T21:47:00Z"])
    def test_common_shapes(self, raw: str) -> None:
        assert _parse_date(raw) == date(2026, 10, 16)

    @pytest.mark.parametrize("raw", [None, "", "null", "not a date"])
    def test_junk_is_none_not_an_exception(self, raw) -> None:
        assert _parse_date(raw) is None


# ==================================================================== location


class TestLocation:
    def test_country_is_the_iso_code(self) -> None:
        label, country, city, region, postal, street = _extract_location(
            {"jobLocation": POSTING["jobLocation"]}
        )
        assert country == "PT"
        assert (city, region) == ("Lisboa", "Lisboa")
        assert label == "Lisboa"
        assert postal == "Lisboa"

    def test_missing_location_is_not_an_error(self) -> None:
        assert _extract_location({}) == (None, None, None, None, None, None)


# ====================================================================== parser


class TestParser:
    def test_a_full_posting_is_parsed(self) -> None:
        job = NetEmpregosParser().parse(
            "16131249",
            detail_html(),
            url="https://www.net-empregos.com/jobs/16131249/x/",
        )
        assert job.source_job_id == "16131249"
        assert job.title.startswith("Especialista")
        assert job.company_name == "Workster"
        assert job.company_logo_url is not None
        assert (job.country, job.city, job.region) == ("PT", "Lisboa", "Lisboa")
        assert job.posted_date == date(2026, 10, 16)
        assert job.closing_date == date(2026, 11, 15)
        assert job.employment_type == "FULL_TIME"
        assert job.industry == "Call Center / Help Desk"

    def test_the_url_id_is_the_key_because_there_is_no_identifier(self) -> None:
        """0 of 3 measured postings carry one."""
        job = NetEmpregosParser().parse("16131249", detail_html())
        assert job.source_job_id == "16131249"
        assert job.raw["has_identifier"] is False

    def test_absent_base_salary_is_recorded_not_silently_ignored(self) -> None:
        job = NetEmpregosParser().parse("16131249", detail_html())
        assert job.raw["has_base_salary"] is False

    def test_an_imagobject_logo_is_accepted_too(self) -> None:
        payload = {
            **POSTING,
            "hiringOrganization": {
                "@type": "Organization",
                "name": "X",
                "logo": {"@type": "ImageObject", "url": "https://x/l.png"},
            },
        }
        assert (
            NetEmpregosParser().parse("1", detail_html(payload)).company_logo_url
            == "https://x/l.png"
        )

    def test_no_title_raises(self) -> None:
        with pytest.raises(NetEmpregosParseError, match="no title"):
            NetEmpregosParser().parse("1", detail_html({}))

    def test_parse_many_collects_failures_rather_than_raising(self) -> None:
        records = [{"job_id": "1", "html": detail_html()}, {"job_id": "2", "html": detail_html({})}]
        jobs, issues = NetEmpregosParser().parse_many(records)
        assert [j.source_job_id for j in jobs] == ["1"]
        assert len(issues) == 1


# ====================================================================== cleaner


class TestCleaner:
    def _job(self, **kw):
        return NetEmpregosParser().parse("16131249", detail_html()).model_copy(update=kw)

    def test_no_salary_is_ever_claimed(self) -> None:
        """Net-Empregos publishes none. Asserting a period about a figure that
        does not exist is a small lie a later analysis cannot see."""
        cleaned = NetEmpregosCleaner().clean_job(self._job())
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False
        assert cleaned.raw_payload["salary_published"] is False

    def test_country_only_location_is_kept(self) -> None:
        job = self._job(location=None, country="PT", city=None)
        assert NetEmpregosCleaner().clean_job(job).location_cleaned == "PT"

    def test_html_is_stripped_from_the_description(self) -> None:
        body = NetEmpregosCleaner().clean_job(self._job()).description_clean
        assert body and "<b>" not in body and "<BR>" not in body

    def test_language_is_recorded_as_portuguese(self) -> None:
        assert NetEmpregosCleaner().clean_job(self._job()).raw_payload["language"] == "pt"

    def test_skills_are_empty_because_the_board_has_none(self) -> None:
        assert NetEmpregosCleaner().clean_job(self._job()).skills == []

    def test_company_whitespace_is_collapsed(self) -> None:
        job = self._job(company_name="Workster  \n Ltd")
        assert NetEmpregosCleaner().clean_job(job).company_name == "Workster Ltd"

    def test_quality_score_ignores_salary_entirely(self) -> None:
        """Every other source's score counts it; including it here would
        depress every row by 1/8 for a fact about the board."""
        cleaned = NetEmpregosCleaner().clean_job(self._job())
        assert 0.0 <= cleaned.data_quality_score <= 1.0
        assert cleaned.data_quality_score > 0.5


class TestEmploymentTypeMapping:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("FULL_TIME", "full_time"),
            ("PART_TIME", "part_time"),
            ("CONTRACT", "contract"),
            ("CONTRACTOR", "freelance"),
            ("TEMPORARY", "temporary"),
            ("INTERN", "internship"),
        ],
    )
    def test_schema_vocabulary_maps_to_database_codes(self, raw, expected) -> None:
        assert _map_employment_type(raw) == expected

    def test_unknown_is_none(self) -> None:
        assert _map_employment_type("NEW") is None
        assert _map_employment_type(None) is None


# ==================================================================== validator


class TestValidator:
    def _report(self, n: int = 18, posting: dict | None = None):
        from job_market_intel.validation.net_empregos_validator import (
            NetEmpregosBatchValidator,
        )

        parser = NetEmpregosParser()
        raw = [{"job_id": str(16131200 + i), "html": detail_html(posting)} for i in range(n)]
        parsed = [parser.parse(r["job_id"], r["html"]) for r in raw]
        return NetEmpregosBatchValidator().validate(raw, parsed)

    def test_a_full_batch_passes(self) -> None:
        assert self._report().passed

    def test_a_very_short_description_counts_as_missing(self) -> None:
        """The floor must still catch a real extraction failure.

        Note this shows up in the field census, not in ``passed``:
        ``validate_batch`` only fails on record counts, skip rate and duplicate
        ids. The census is where a per-field regression becomes visible.
        """
        report = self._report(posting={**POSTING, "description": ""})
        assert report.missing_field_rates.get("description") == 1.0

    def test_absent_location_is_counted_but_not_fatal(self) -> None:
        payload = {k: v for k, v in POSTING.items() if k != "jobLocation"}
        report = self._report(posting=payload)
        assert report.passed
        assert report.missing_field_rates.get("location") == 1.0

    def test_no_salary_is_ever_reported_missing(self) -> None:
        """A salary check here would be a permanent 100% failure saying nothing."""
        rates = self._report().missing_field_rates
        assert "salary" not in rates

    def test_a_thin_batch_does_fail(self) -> None:
        assert not self._report(n=3).passed


# ==================================================================== settings


class TestSettings:
    def test_defaults(self) -> None:
        s = NetEmpregosSettings()
        assert s.base_url == "https://www.net-empregos.com"
        assert s.listing_path == "/jobs"
        assert s.max_jobs_per_run == 150

    def test_overrides_are_honoured(self) -> None:
        s = NetEmpregosSettings(max_pages=3, max_jobs_per_run=25)
        assert (s.max_pages, s.max_jobs_per_run) == (3, 25)

    def test_settings_reject_nonsense_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            NetEmpregosSettings(inter_request_delay_seconds=-1.0)
        with pytest.raises(ValidationError):
            NetEmpregosSettings(max_jobs_per_run=0)
